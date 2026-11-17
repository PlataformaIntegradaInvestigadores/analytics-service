import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import pytest
from pypdf import PdfWriter

from app.data.pdf_text import CONFIG, PdfTextStore, extract_pdf
from app.domain.common import AnalyticsError, fingerprint
from app.pdftext import main, run_batch


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "input"
    root.mkdir()
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.write(root / "blank.pdf")
    return (
        root,
        tmp_path / "registry.sqlite",
        [{"document_id": "fixture:blank", "file": "blank.pdf"}],
    )


def test_actual_reference_pdf_roundtrip(tmp_path):
    # Uses an existing real reference, never fabricates scientific documents.
    root = Path(__file__).resolve().parents[2] / "papers"
    path = root / "04_Grootendorst_2022_BERTopic.pdf"
    if not path.is_file():
        pytest.skip("Local reference PDF is not distributed with the repository")
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    registry = tmp_path / "registry.sqlite"
    entries = [{"document_id": "reference:bertopic", "file": path.name}]
    first = run_batch(root, entries, registry)
    record = first["documents"][0]
    assert record["status"] in ("extracted", "partial_text")
    assert record["characters"] > 1000 and first["corpus_adopted"] is False
    stored = PdfTextStore(registry).load(record["artifact_id"])
    assert "BERTopic" in stored["extraction"]["pages"][0]["text"]
    with patch("app.pdftext.subprocess.run", side_effect=AssertionError("must reuse")):
        assert run_batch(root, entries, registry)["documents"][0]["reused"]
    assert before == hashlib.sha256(path.read_bytes()).hexdigest()


def test_no_text_reuse_encryption_and_corruption(source):
    root, registry, entries = source
    result = run_batch(root, entries, registry)["documents"][0]
    assert result["status"] == "no_extractable_text"
    assert run_batch(root, entries, registry)["documents"][0]["reused"]
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.encrypt("not-supplied")
    writer.write(root / "encrypted.pdf")
    assert extract_pdf(root / "encrypted.pdf")["status"] == "encrypted"
    with closing(sqlite3.connect(registry)) as db, db:
        db.execute("UPDATE pdf_text SET payload='{}'")
    assert (
        run_batch(root, entries, registry)["documents"][0]["status"]
        == "pdf_artifact_integrity"
    )


def test_bad_inputs_and_limits(source):
    root, registry, entries = source
    for batch in ([], [{}], [{"document_id": ""}], entries * 2):
        with pytest.raises(AnalyticsError):
            run_batch(root, batch, registry)
    for timeout in (0, 301):
        with pytest.raises(AnalyticsError):
            run_batch(root, entries, registry, timeout)
    with pytest.raises(AnalyticsError):
        run_batch(root, entries, root / "registry.sqlite")
    for filename, expected in (
        ("../other.pdf", "unsafe_pdf_path"),
        ("missing.pdf", "unreadable_pdf"),
        ("wrong.txt", "unsafe_pdf_path"),
    ):
        assert (
            run_batch(root, [{"document_id": "x", "file": filename}], registry)[
                "documents"
            ][0]["status"]
            == expected
        )
    (root / "bad.pdf").write_bytes(b"not a PDF")
    assert (
        run_batch(root, [{"document_id": "bad", "file": "bad.pdf"}], registry)[
            "documents"
        ][0]["status"]
        == "invalid_pdf"
    )
    (root / "bad.pdf").write_bytes(b"%PDF-broken")
    assert (
        run_batch(root, [{"document_id": "bad", "file": "bad.pdf"}], registry)[
            "documents"
        ][0]["status"]
        == "pdf_worker_failed"
    )
    with patch.dict(CONFIG, {"max_pages": 0}), pytest.raises(AnalyticsError):
        extract_pdf(root / "blank.pdf")
    with patch.dict(CONFIG, {"max_bytes": 1}), pytest.raises(AnalyticsError):
        extract_pdf(root / "blank.pdf")


def test_timeout_continues_and_cli(source, capsys):
    import subprocess

    root, registry, entries = source
    with patch(
        "app.pdftext.subprocess.run", side_effect=subprocess.TimeoutExpired("worker", 1)
    ):
        assert run_batch(root, entries, registry)["documents"][0]["status"] == "timeout"
    manifest = root.parent / "manifest.json"
    manifest.write_text(json.dumps(entries))
    assert (
        main(
            [
                "batch",
                "--root",
                str(root),
                "--manifest",
                str(manifest),
                "--registry",
                str(registry),
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    identifier = report["documents"][0]["artifact_id"]
    assert main(["show", "--registry", str(registry), "--id", identifier]) == 0
    assert main(["show", "--registry", str(registry), "--id", "absent"]) == 2
    assert main(["show", "--registry", str(root / "absent"), "--id", "absent"]) == 2
    stored = PdfTextStore(registry).load(identifier)
    assert fingerprint(stored["extraction"]) == stored["extraction_sha256"]
