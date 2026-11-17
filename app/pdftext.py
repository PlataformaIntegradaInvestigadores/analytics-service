"""Preparatory local extraction: python -m app.pdftext --help."""

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from app.core.json_io import read_json_file
from app.data.pdf_text import CONFIG, PdfTextStore, configuration, extract_pdf
from app.domain.common import AnalyticsError, canonical_json, fingerprint


def run_batch(root, entries, registry, timeout=90):
    root = Path(root).resolve()
    registry = Path(registry).resolve()
    if (
        not root.is_dir()
        or registry.is_relative_to(root)
        or not 1 <= timeout <= 300
        or not isinstance(entries, list)
        or not 1 <= len(entries) <= 10000
    ):
        raise AnalyticsError(
            "invalid_pdf_batch",
            "Use an input directory, external registry and bounded batch",
        )
    keys = [entry.get("document_id") for entry in entries if isinstance(entry, dict)]
    if (
        len(keys) != len(entries)
        or any(not isinstance(k, str) or not k.strip() or len(k) > 256 for k in keys)
        or len(set(keys)) != len(keys)
    ):
        raise AnalyticsError(
            "invalid_pdf_manifest", "Unique explicit document IDs required"
        )
    store = PdfTextStore(registry)
    reports = []
    for entry in entries:
        report = {
            "document_id": entry["document_id"],
            "purpose": "preparation_only",
            "reused": False,
        }
        try:
            relative = Path(entry["file"])
            source = (root / relative).resolve()
            if (
                relative.is_absolute()
                or not source.is_relative_to(root)
                or source.suffix.lower() != ".pdf"
            ):
                raise AnalyticsError(
                    "unsafe_pdf_path", "Manifest path must stay inside input root"
                )
            with source.open("rb") as stream:
                raw = stream.read(CONFIG["max_bytes"] + 1)
            if len(raw) > CONFIG["max_bytes"] or not raw.startswith(b"%PDF-"):
                raise AnalyticsError("invalid_pdf", "Expected bounded PDF bytes")
            source_hash = hashlib.sha256(raw).hexdigest()
            key = fingerprint(
                {"source_sha256": source_hash, "configuration": configuration()}
            )
            # Key is distinct from content ID: cache index stored as verified envelope.
            cached = store.load(key)
            if cached is not None:
                result = cached["extraction"]
                report["reused"] = True
            else:
                with tempfile.TemporaryDirectory(
                    prefix="pdf-extraction-", dir=registry.parent
                ) as folder:
                    snapshot = Path(folder) / "source.pdf"
                    snapshot.write_bytes(raw)
                    completed = subprocess.run(
                        [sys.executable, "-m", "app.pdftext", "_worker", str(snapshot)],
                        capture_output=True,
                        timeout=timeout,
                        check=False,
                    )
                if completed.returncode != 0:
                    raise AnalyticsError(
                        "pdf_worker_failed", "PDF worker failed without publishing text"
                    )
                result = json.loads(completed.stdout.decode("utf-8"))
                if (
                    result["source_sha256"] != source_hash
                    or result["configuration"] != configuration()
                ):
                    raise AnalyticsError(
                        "source_changed", "Worker source/configuration mismatch"
                    )
                store.save(
                    key,
                    {
                        "status": result["status"],
                        "source_sha256": source_hash,
                        "configuration": configuration(),
                        "extraction": result,
                    },
                )
            report.update(
                {
                    "artifact_id": key,
                    "source_sha256": source_hash,
                    "status": result["status"],
                    "page_count": result["page_count"],
                    "text_pages": sum(p["status"] == "text" for p in result["pages"]),
                    "characters": sum(len(p["text"]) for p in result["pages"]),
                }
            )
        except subprocess.TimeoutExpired:
            report["status"] = "timeout"
        except (AnalyticsError, OSError, ValueError, KeyError, TypeError) as exc:
            report["status"] = getattr(exc, "code", "unreadable_pdf")
        reports.append(report)
    return {
        "purpose": "preparation_only",
        "corpus_adopted": False,
        "documents": reports,
    }


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    worker = commands.add_parser("_worker", help=argparse.SUPPRESS)
    worker.add_argument("file", type=Path)
    batch = commands.add_parser("batch")
    batch.add_argument("--root", type=Path, required=True)
    batch.add_argument("--manifest", type=Path, required=True)
    batch.add_argument("--registry", type=Path, required=True)
    batch.add_argument("--timeout", type=int, default=90)
    show = commands.add_parser("show")
    show.add_argument("--registry", type=Path, required=True)
    show.add_argument("--id", required=True)
    args = parser.parse_args(argv)
    try:
        if args.operation == "_worker":
            result = extract_pdf(args.file)
        elif args.operation == "batch":
            result = run_batch(
                args.root, read_json_file(args.manifest), args.registry, args.timeout
            )
        else:
            if not args.registry.is_file():
                raise AnalyticsError(
                    "pdf_registry_missing", "Extraction registry does not exist"
                )
            result = PdfTextStore(args.registry).load(args.id)
            if result is None:
                raise AnalyticsError("pdf_artifact_missing", "Unknown extraction")
        # Text only printed when explicitly requesting an artifact or in worker pipe.
        print(canonical_json(result))
        return 0
    except Exception as exc:
        print(canonical_json({"status": getattr(exc, "code", "pdf_processing_failed")}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
