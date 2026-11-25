"""Audit contracts on bounded fixtures, separate from empirical thesis results."""

import json
import sqlite3
import sys

import pyarrow as pa
import pytest

from app.core.provenance import sha256_file
from app.data.layers import LayerStore
from app.domain.common import canonical_json, fingerprint
from app.forecast_audit import _equivalent, audit, main
from app.research_execution import forecast_study
from app.schemas.study import StudyProtocol


def test_cli_replays_published_models_and_rejects_changed_study(tmp_path, monkeypatch):
    protocol = StudyProtocol(
        start_year=2000,
        topic_fit_end=2008,
        validation_end=2010,
        test_end=2012,
        approval_reference="technical audit fixture",
        rationale="Bounded annual fixture for verifying the audit contract.",
    )
    series = {
        "topic-0": [
            {"year": year, "count": (year - 1998) ** 2} for year in range(2000, 2013)
        ]
    }
    prediction, models = forecast_study(series, protocol)
    study = {
        "run_id": "fixture-study",
        "topic_model_id": "fixture-nmf",
        "protocol": protocol.model_dump(),
        "preparation": {},
        "topics": [],
        "series": series,
        "prediction": prediction,
    }
    study["report_sha256"] = fingerprint(study)
    payload = canonical_json(study)
    database = tmp_path / "study.sqlite"
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE study(id TEXT PRIMARY KEY,payload TEXT)")
        db.execute("INSERT INTO study VALUES (?,?)", (study["run_id"], payload))
        db.execute("CREATE TABLE regressors(id TEXT PRIMARY KEY,payload TEXT)")
        db.executemany(
            "INSERT OR IGNORE INTO regressors VALUES (?,?)",
            [(model["model_id"], canonical_json(model)) for model in models],
        )
    source = tmp_path / "study.json"
    source.write_text(payload, encoding="utf8")
    plan = tmp_path / "plan.txt"
    plan.write_text("Technical fixture plan", encoding="utf8")
    archive = LayerStore(tmp_path / "layers", create=True)
    release = archive.publish(
        {
            "gold_annual_series": {
                "layer": "gold",
                "schema": pa.schema(
                    [
                        ("topic_id", pa.string()),
                        ("year", pa.int64()),
                        ("count", pa.int64()),
                    ]
                ),
                "batches": [
                    [{"topic_id": "topic-0", **point} for point in series["topic-0"]]
                ],
            }
        },
        {"study_results": {"layer": "gold", "path": source}},
        {"study_run_id": study["run_id"], "signed_plan_sha256": sha256_file(plan)},
    )
    output = tmp_path / "audit.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "forecast_audit",
            "--store",
            str(archive.root),
            "--database",
            str(database),
            "--plan",
            str(plan),
            "--output",
            str(output),
        ],
    )
    main()
    result = json.loads(output.read_text(encoding="utf8"))
    assert result["status"] == "passed"
    assert result["release_id"] == release["release_id"]
    assert result["target_counts"] == {
        "validation_records": 2,
        "test_records": 2,
        "forecasts": 1,
    }
    assert result["local_explanations_replayed"] == 5
    assert result["current_working_plan_sha256"] == sha256_file(plan)
    assert (
        result["comparison"]["diagnostic"]["overall"]["ridge"]
        == prediction["test"]["ridge"]
    )
    with pytest.raises(FileExistsError):
        main()
    with sqlite3.connect(database) as db:
        db.execute("UPDATE study SET payload='{}'")
    with pytest.raises(ValueError, match="database and release differ"):
        audit(archive.root, database, plan)


@pytest.mark.parametrize(
    "expected,actual", [({"a": 1}, {"b": 1}), ([1], []), (0.5, 0.6), ("one", "two")]
)
def test_audit_rejects_different_structure_and_values(expected, actual):
    with pytest.raises(ValueError, match="Different"):
        _equivalent(expected, actual)


def test_numeric_replay_tolerates_roundoff_and_only_explicit_model_id_changes():
    _equivalent(
        {"model_id": "a", "value": [1.0]},
        {"model_id": "b", "value": [1.0 + 1e-12]},
        compare_ids=False,
    )
    with pytest.raises(ValueError, match="Different"):
        _equivalent({"model_id": "a"}, {"model_id": "b"})
