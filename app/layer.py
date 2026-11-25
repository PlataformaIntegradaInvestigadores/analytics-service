"""Materialize the real Centinela corpus/study into private versioned layers."""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from app.core.json_io import read_json_file
from app.core.provenance import sha256_file, source_files
from app.data.documents import read_database
from app.data.layers import LayerStore
from app.data.research_corpus import SCHEMAS
from app.domain.common import AnalyticsError, canonical_json, fingerprint


def _sql_table(path, table, *, layer, integers=()):
    import pyarrow as pa

    with read_database(path) as db:
        columns = [r[1] for r in db.execute(f'PRAGMA table_info("{table}")')]
        if not columns:
            columns = [
                r[0] for r in db.execute(f'SELECT * FROM "{table}" LIMIT 0').description
            ]
    schema = pa.schema(
        [(c, pa.int64() if c in integers else pa.string()) for c in columns]
    )

    def batches():
        with read_database(path) as db:
            query = db.execute(
                f'SELECT * FROM "{table}" ORDER BY '
                + ",".join('"' + c + '"' for c in columns)
            )
            while rows := query.fetchmany(5000):
                yield [
                    {
                        c: int(value) if c in integers and value is not None else value
                        for c, value in zip(columns, row, strict=True)
                    }
                    for row in rows
                ]

    return {"layer": layer, "schema": schema, "batches": batches()}


def _objects(rows, layer, schema):
    import pyarrow as pa

    return {
        "layer": layer,
        "schema": pa.schema(schema),
        "batches": (rows[i : i + 5000] for i in range(0, len(rows), 5000)),
    }


def _verified_report(path):
    report = read_json_file(path)
    content = {k: v for k, v in report.items() if k != "report_sha256"}
    if fingerprint(content) != report.get("report_sha256"):
        raise AnalyticsError("layer_report_integrity", "Study/review report changed")
    return report


def materialize(
    source_directory,
    corpus,
    study_directory,
    review_directory,
    plan,
    store,
    expected_parent=None,
):
    import pyarrow as pa

    paths = [
        Path(p).resolve()
        for p in (
            source_directory,
            corpus,
            study_directory,
            review_directory,
            plan,
            store,
        )
    ]
    source_directory, corpus, study_directory, review_directory, plan, store = paths
    repository = Path(__file__).resolve().parents[1]
    if store.is_relative_to(repository) or any(
        p.is_relative_to(store) or store.is_relative_to(p) for p in paths[:-1]
    ):
        raise AnalyticsError(
            "unsafe_layer_output", "Store must be external to inputs/repository"
        )
    study = _verified_report(study_directory / "report.json")
    review = _verified_report(review_directory / "report.json")
    if (
        review["identity"]["previous_run_id"] != study["run_id"]
        or sha256_file(corpus) != study["identity"]["source_snapshot_sha256"]
    ):
        raise AnalyticsError(
            "layer_lineage_mismatch", "Use the verified original study snapshot"
        )
    with read_database(corpus) as db:
        manifest = json.loads(db.execute("SELECT payload FROM manifest").fetchone()[0])
    if manifest["use_scope"] != "research_authorized_as_declared":
        raise AnalyticsError(
            "layer_authorization_missing", "Research source declaration required"
        )
    source_hashes = {
        str(source_directory / name): digest
        for name, digest in manifest["source_sha256"].items()
    }
    if any(sha256_file(Path(p)) != digest for p, digest in source_hashes.items()):
        raise AnalyticsError("layer_source_changed", "Raw CSV differs from snapshot")
    source_hashes.update(
        {str(corpus): sha256_file(corpus), str(plan): sha256_file(plan)}
    )
    tables = {
        "bronze_"
        + name: _sql_table(
            corpus, "raw_" + name, layer="bronze", integers=("_input_row",)
        )
        for name in SCHEMAS
    }
    tables["silver_articles"] = _sql_table(
        corpus, "articles", layer="silver", integers=("year",)
    )
    for name in (
        "articles_authors",
        "articles_affiliations",
        "articles_author_keywords",
        "authors_affiliations",
    ):
        tables["silver_" + name] = _sql_table(corpus, "valid_" + name, layer="silver")
    prepared = study_directory / "prepared.sqlite"
    source_hashes[str(prepared)] = sha256_file(prepared)
    tables["silver_prepared_documents"] = _sql_table(
        prepared, "prepared", layer="silver", integers=("year",)
    )
    tables["silver_topic_assignments"] = _sql_table(
        prepared, "assignments", layer="silver"
    )
    series = [
        {
            "topic_id": topic,
            "year": p["year"],
            "count": p["count"],
            "denominator": p["denominator"],
            "share": p["share"],
            "coverage": p["coverage"],
            "unassigned_documents": p["unassigned_documents"],
        }
        for topic, points in sorted(study["series"].items())
        for p in points
    ]
    tables["gold_annual_series"] = _objects(
        series,
        "gold",
        [
            ("topic_id", pa.string()),
            ("year", pa.int64()),
            ("count", pa.int64()),
            ("denominator", pa.int64()),
            ("share", pa.float64()),
            ("coverage", pa.string()),
            ("unassigned_documents", pa.int64()),
        ],
    )
    forecasts = [
        {
            **r,
            "partition": (
                "development"
                if r["year"] <= 2018
                else "previously_observed_exploratory"
            ),
        }
        for candidate in review["forecast"]["candidates"]
        for r in candidate["records"]
    ]
    tables["gold_forecast_comparison"] = _objects(
        forecasts,
        "gold",
        [
            ("candidate_id", pa.string()),
            ("topic_id", pa.string()),
            ("year", pa.int64()),
            ("observed", pa.int64()),
            ("prediction", pa.float64()),
            ("model_id", pa.string()),
            ("trained_through", pa.int64()),
            ("partition", pa.string()),
        ],
    )
    topics = [
        {
            "candidate_id": c["candidate_id"],
            "model_id": c["model_id"],
            "training_json": canonical_json(c["training"]),
            "validation_json": canonical_json(c["validation"]),
        }
        for c in review["topics"]["candidates"]
    ]
    tables["gold_topic_comparison"] = _objects(
        topics,
        "gold",
        [
            ("candidate_id", pa.string()),
            ("model_id", pa.string()),
            ("training_json", pa.string()),
            ("validation_json", pa.string()),
        ],
    )
    blobs = {
        "bronze_"
        + name
        + "_csv": {"layer": "bronze", "path": source_directory / (name + ".csv")}
        for name in SCHEMAS
    }
    for name, layer, path in (
        ("study_topic_models", "models", study_directory / "models.sqlite"),
        ("study_results", "gold", study_directory / "report.json"),
        ("study_protocol", "silver", study_directory / "protocol.json"),
        ("review_topic_models", "models", review_directory / "new-topic-models.sqlite"),
        ("review_lda_model", "models", review_directory / "lda-model.json"),
        ("review_forecast_models", "models", review_directory / "forecast-models.json"),
        ("review_results", "gold", review_directory / "report.json"),
        ("review_protocol", "silver", review_directory / "protocol.json"),
        ("review_catalog", "gold", review_directory / "private-topic-catalog.json"),
        ("review_audit_cases", "silver", review_directory / "private-audit-cases.json"),
    ):
        blobs[name] = {"layer": layer, "path": path}
        source_hashes[str(path)] = sha256_file(path)
    lineage = {
        "dataset": manifest["source_version"],
        "source_sha256": manifest["source_sha256"],
        "source_snapshot_sha256": source_hashes[str(corpus)],
        "signed_plan_sha256": source_hashes[str(plan)],
        "study_run_id": study["run_id"],
        "review_run_id": review["run_id"],
        "study_report_sha256": sha256_file(study_directory / "report.json"),
        "review_report_sha256": sha256_file(review_directory / "report.json"),
        "software_sha256": fingerprint(source_files()),
        "scope": "research_authorized_as_declared; private local layers",
        "date_semantics": "publication year retrospective; first indexed date unknown",
        "neo4j_mongodb": "existing operational stores not replaced or mutated",
    }
    archive = LayerStore(store, create=True)
    result = archive.publish(
        tables,
        blobs,
        lineage,
        expected_parent=expected_parent,
        source_hashes=source_hashes,
    )
    verification = archive.verify(result["release_id"])
    return {
        **verification,
        "source_articles": result["tables"]["silver_articles"]["rows"],
        "release": result,
        "source_hashes_unchanged": True,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    publish = commands.add_parser("materialize")
    for name in (
        "source-directory",
        "corpus",
        "study-directory",
        "review-directory",
        "plan",
        "store",
    ):
        publish.add_argument("--" + name, type=Path, required=True)
    publish.add_argument("--expected-parent")
    verify = commands.add_parser("verify")
    verify.add_argument("--store", type=Path, required=True)
    verify.add_argument("--release")
    args = parser.parse_args(argv)
    try:
        if args.command == "verify":
            result = LayerStore(args.store).verify(args.release)
        else:
            result = materialize(
                args.source_directory,
                args.corpus,
                args.study_directory,
                args.review_directory,
                args.plan,
                args.store,
                args.expected_parent,
            )
        print(canonical_json(result))
        return 0
    except (AnalyticsError, OSError, sqlite3.Error, ValueError) as exc:
        print(
            canonical_json(
                {"error": getattr(exc, "code", "invalid_layers"), "message": str(exc)}
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
