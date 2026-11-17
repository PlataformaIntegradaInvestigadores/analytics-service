"""Real local references only; export aggregate preparation evidence, never text."""

import argparse
import json
from pathlib import Path

from app.core.provenance import sha256_file
from app.pdftext import run_batch

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--root", type=Path, required=True)
parser.add_argument("--registry", type=Path, required=True)
parser.add_argument("--report", type=Path, required=True)
args = parser.parse_args()
files = sorted(args.root.glob("*.pdf"))
if not files or args.report.exists():
    parser.error("Use existing reference PDFs and a new report path")
before = {p.name: sha256_file(p) for p in files}
entries = [{"document_id": "reference:" + p.stem, "file": p.name} for p in files]
first = run_batch(args.root, entries, args.registry)
second = run_batch(args.root, entries, args.registry)
unchanged = before == {p.name: sha256_file(p) for p in files}
valid = all(d["status"] in ("extracted", "partial_text") for d in first["documents"])
resumed = all(d["reused"] for d in second["documents"])
report = {
    "status": "passed" if unchanged and valid and resumed else "failed",
    "purpose": "preparation_only",
    "source_kind": "existing_bibliographic_references",
    "corpus_adopted": False,
    "training_executed": False,
    "originals_unchanged": unchanged,
    "resume_verified": resumed,
    "source_sha256": before,
    "documents": first["documents"],
}
args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
print(
    json.dumps(
        {k: report[k] for k in ("status", "originals_unchanged", "resume_verified")}
    )
)
raise SystemExit(0 if report["status"] == "passed" else 1)
