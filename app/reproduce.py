"""One technical rehearsal: python -m app.reproduce --output EXTERNAL_NEW_DIR."""

import argparse
import json
import platform
import sqlite3
import tempfile
import time
from contextlib import closing
from pathlib import Path

from app.application.modeling import bertopic_capability, fit_nmf, infer_nmf
from app.core.provenance import source_files
from app.data.models import ModelStore
from app.data.versioned_tables import VersionedTable
from app.domain.common import canonical_json, fingerprint
from app.domain.explainability import explanation_contract
from app.domain.temporal import aggregate


def storage_benchmark(root):
    """Comparable controlled rows, elapsed wall time and on-disk bytes only."""
    records = [{"document_id": str(i), "year": 2020 + i % 6} for i in range(5000)]
    table = VersionedTable(root / "benchmark-parquet")
    started = time.perf_counter()
    identifier = table.commit(records)
    parquet_write = time.perf_counter() - started
    started = time.perf_counter()
    assert len(table.read(identifier, ["document_id"])) == len(records)
    parquet_read = time.perf_counter() - started
    path = root / "benchmark.sqlite"
    started = time.perf_counter()
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE documents (document_id TEXT, year INTEGER)")
        db.executemany("INSERT INTO documents VALUES (:document_id,:year)", records)
    sqlite_write = time.perf_counter() - started
    started = time.perf_counter()
    with closing(sqlite3.connect(path)) as db:
        assert len(db.execute("SELECT document_id FROM documents").fetchall()) == len(
            records
        )
    return {
        "controlled_rows": len(records),
        "sqlite": {
            "write_seconds": sqlite_write,
            "projection_seconds": time.perf_counter() - started,
            "bytes": path.stat().st_size,
        },
        "parquet_catalog": {
            "write_seconds": parquet_write,
            "projection_seconds": parquet_read,
            "bytes": sum(p.stat().st_size for p in table.root.iterdir()),
        },
        "decision": "feasibility_only_not_production_selection",
        "limits": (
            "Single process, warm imports; no concurrency, RSS or distributed test"
        ),
    }


def rehearse(root):
    root = Path(root)
    texts = [
        "solar energy sunlight renewable panel",
        "solar panel energy renewable power",
        "wind renewable energy sunlight solar",
        "neural network machine learning model",
        "machine learning neural model training",
        "deep neural network learning training",
    ]
    documents = [
        {"document_id": str(i), "text": text, "publication_date": f"202{i // 2}-01-01"}
        for i, text in enumerate(texts)
    ]
    started = time.perf_counter()
    model = fit_nmf(
        documents,
        [d["document_id"] for d in documents],
        workset_id=fingerprint(documents),
        topics=2,
        software=source_files(),
    )
    registry = ModelStore(root / "models.sqlite")
    registry.save(model)
    inferred = infer_nmf(registry.load(model["model_id"]), documents)
    rows = [
        {"document_id": d["document_id"], "topic_id": d["topic_id"]} for d in inferred
    ]
    table = VersionedTable(root / "table-prototype")
    first = table.commit(rows)
    second = table.commit(
        [{**row, "technical": True} for row in rows], expected_parent=first
    )
    assert table.read(first) == rows
    assert len(table.read(second, ["document_id"])) == len(rows)
    series = aggregate(
        documents,
        {d["document_id"]: d["topic_id"] for d in inferred},
        granularity="year",
        precision="year",
    )
    contract = explanation_contract(
        model_id="controlled-linear-fixture",
        features=["lag"],
        training_features=["lag"],
        row=[1.0],
        prediction=2.0,
        target="documents",
        method="linear_exact",
        model_family="linear",
    )
    return {
        "status": "passed",
        "data_kind": "controlled_fixture",
        "empirical_training": False,
        "model_id": model["model_id"],
        "model_roundtrip": True,
        "fit_documents": len(documents),
        "table_versions": [first, second],
        "table_history_verified": True,
        "table_backend": "local_parquet_sqlite_catalog_feasibility_only",
        "storage_benchmark": storage_benchmark(root),
        "annual_periods": len(series),
        "unknown_coverage_preserved": True,
        "xai_contract_status": contract["status"],
        "bertopic": bertopic_capability(),
        "elapsed_seconds": time.perf_counter() - started,
        "python": platform.python_version(),
        "library_versions": model["versions"],
        "limitations": [
            "not final research evidence",
            "no operational gateway/identity",
            "no trained BERTopic or explainer",
            "not a production Lakehouse",
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error(
            "Choose a new output directory; existing evidence is never overwritten"
        )
    args.output.mkdir(parents=True)
    # Intermediate artifacts remain ephemeral; export only aggregate evidence.
    with tempfile.TemporaryDirectory(dir=args.output) as folder:
        report = rehearse(folder)
    (args.output / "report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print(canonical_json(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
