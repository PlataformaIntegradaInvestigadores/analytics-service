"""Local preparatory PDF extraction; artifacts do not enter the training corpus."""

import hashlib
import json
import logging
import sqlite3
from contextlib import closing
from importlib.metadata import version
from pathlib import Path

from app.domain.common import AnalyticsError, canonical_json, fingerprint

VERSION = "pdf-text-pages-v1"
CONFIG = {
    "max_bytes": 50 * 1024 * 1024,
    "max_pages": 500,
    "max_characters": 2_000_000,
    "max_page_stream": 10 * 1024 * 1024,
}
SUCCESS = {"extracted", "partial_text", "no_extractable_text", "encrypted"}


def configuration():
    return {
        "algorithm": VERSION,
        "source_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "parser": "pypdf",
        "parser_version": version("pypdf"),
        "limits": CONFIG,
        "purpose": "preparation_only",
        "ocr": "not_implemented",
    }


def extract_pdf(path):
    """Called in an isolated worker; never changes or decrypts the input file."""
    from pypdf import PdfReader

    logging.getLogger("pypdf").setLevel(logging.ERROR)
    raw = Path(path).read_bytes()
    if len(raw) > CONFIG["max_bytes"] or not raw.startswith(b"%PDF-"):
        raise AnalyticsError("invalid_pdf", "Expected bounded PDF bytes")
    import io

    reader = PdfReader(io.BytesIO(raw), strict=False)
    result = {
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "configuration": configuration(),
        "pages": [],
    }
    if reader.is_encrypted:
        return {**result, "status": "encrypted", "page_count": None}
    if len(reader.pages) > CONFIG["max_pages"]:
        raise AnalyticsError("page_limit", "PDF exceeds page limit")
    characters = 0
    for number, page in enumerate(reader.pages, 1):
        content = page.get_contents()
        if content is not None and len(content.get_data()) > CONFIG["max_page_stream"]:
            raise AnalyticsError("stream_limit", "Page stream exceeds limit")
        try:
            text = (page.extract_text() or "").replace("\r\n", "\n").replace("\r", "\n")
            status = "text" if text.strip() else "no_extractable_text"
        except Exception:
            text, status = "", "extraction_error"
        characters += len(text)
        if characters > CONFIG["max_characters"]:
            raise AnalyticsError("text_limit", "Extracted text exceeds limit")
        result["pages"].append(
            {
                "number": number,
                "text": text,
                "status": status,
                "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
            }
        )
    states = {p["status"] for p in result["pages"]}
    status = (
        "extracted"
        if states == {"text"}
        else (
            "partial_text"
            if "text" in states
            else (
                "extraction_error"
                if "extraction_error" in states
                else "no_extractable_text"
            )
        )
    )
    return {**result, "status": status, "page_count": len(reader.pages)}


class PdfTextStore:
    def __init__(self, path):
        self.path = Path(path).resolve()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS pdf_text "
                "(id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
            )

    def load(self, identifier):
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute(
                "SELECT payload FROM pdf_text WHERE id=?", (identifier,)
            ).fetchone()
        if row is None:
            return None
        try:
            result = json.loads(row[0])
            if (
                fingerprint(
                    {
                        "source_sha256": result["source_sha256"],
                        "configuration": result["configuration"],
                    }
                )
                != identifier
                or fingerprint(result["extraction"]) != result["extraction_sha256"]
                or result["extraction"]["source_sha256"] != result["source_sha256"]
                or result["extraction"]["configuration"] != result["configuration"]
                or result["status"] != result["extraction"]["status"]
            ):
                raise ValueError("Digest mismatch")
        except (ValueError, TypeError, KeyError) as exc:
            raise AnalyticsError(
                "pdf_artifact_integrity", "Stored extraction was altered"
            ) from exc
        return result

    def save(self, identifier, result):
        if result["status"] not in SUCCESS:
            return
        result = {**result, "extraction_sha256": fingerprint(result["extraction"])}
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                "INSERT OR IGNORE INTO pdf_text VALUES (?,?)",
                (identifier, canonical_json(result)),
            )
        if self.load(identifier) != result:
            raise AnalyticsError(
                "pdf_artifact_integrity", "Extraction identity collision"
            )
