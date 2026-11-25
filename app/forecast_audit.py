"""Replay published annual forecasts and XAI against the original research artifacts."""

import argparse
import json
import math
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.provenance import sha256_file, source_files
from app.data.documents import read_database
from app.data.layers import LayerStore
from app.domain.annual_prediction import annual_rows, explain_prediction
from app.domain.common import fingerprint
from app.main import create_app
from app.research_execution import forecast_study
from app.schemas.study import StudyProtocol


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _equivalent(expected, actual, path="prediction", *, compare_ids=True):
    if isinstance(expected, dict) and isinstance(actual, dict):
        _require(expected.keys() == actual.keys(), f"Different fields at {path}")
        for name, value in expected.items():
            if name != "model_id" or compare_ids:
                _equivalent(
                    value, actual[name], f"{path}.{name}", compare_ids=compare_ids
                )
    elif isinstance(expected, list) and isinstance(actual, list):
        _require(len(expected) == len(actual), f"Different lengths at {path}")
        for i, (a, b) in enumerate(zip(expected, actual, strict=True)):
            _equivalent(a, b, f"{path}[{i}]", compare_ids=compare_ids)
    elif isinstance(expected, float) and isinstance(actual, (int, float)):
        _require(
            math.isclose(expected, actual, rel_tol=1e-9, abs_tol=1e-10),
            f"Different value at {path}",
        )
    else:
        _require(expected == actual, f"Different value at {path}")


def audit(store, database, plan):
    archive = LayerStore(store)
    tracked = (archive.catalog, database, plan)
    before = {item: sha256_file(item) for item in tracked}
    release = archive.release()
    release_id = release["release_id"]
    stored = json.loads(archive.read_blob(release, "study_results"))
    with read_database(database) as db:
        report = db.execute(
            "SELECT payload FROM study WHERE id=?", (stored["run_id"],)
        ).fetchone()
        _require(
            report is not None and json.loads(report[0]) == stored,
            "Study database and release differ",
        )
        models = {
            model_id: json.loads(payload)
            for model_id, payload in db.execute("SELECT id,payload FROM regressors")
        }

    with TestClient(create_app(Settings(lake_directory=store))) as client:
        response = client.get("/api/v1/study", params={"release_id": release_id})
        response.raise_for_status()
        data = response.json()
    _require(
        data["storage_lineage"]["release_id"] == release_id, "Incorrect API release"
    )
    series = data["series"]
    _equivalent(stored["series"], series, "series")
    prediction = data["prediction"]
    _equivalent(stored["prediction"], prediction)
    protocol = StudyProtocol.model_validate(stored["protocol"])

    rows = [
        {"topic_id": topic, **row}
        for topic, points in sorted(series.items())
        for row in annual_rows(points)
    ]
    targets = {(row["topic_id"], row["year"]): row for row in rows}
    counts = {}
    for partition in ("validation_records", "test_records", "forecasts"):
        for record in prediction[partition]:
            key = (record["topic_id"], record["year"])
            row = targets[key]
            model = models[record["model_id"]]
            training = [entry for entry in rows if entry["year"] < row["year"]]
            _require(
                model["model_id"] == record["model_id"]
                and model["training_sha256"] == fingerprint(training)
                and model["training_rows"] == len(training)
                and model["trained_through"] == row["observed_through"],
                f"Training lineage mismatch for {key}",
            )
            _equivalent(record, {"topic_id": key[0], **explain_prediction(model, row)})
        counts[partition] = len(prediction[partition])

    replay, replay_models = forecast_study(series, protocol)
    # A numeric replay on a different BLAS build can have a different binary hash.
    _equivalent(prediction, replay, compare_ids=False)
    for model in replay_models:
        original = next(
            m
            for m in models.values()
            if m["trained_through"] == model["trained_through"]
        )
        _equivalent(original, model, "regressor", compare_ids=False)
    _require(
        all(sha256_file(item) == before[item] for item in tracked),
        "An input changed during verification",
    )
    return {
        "status": "passed",
        "release_id": release_id,
        "study_run_id": data["run_id"],
        "topic_model_id": data["topic_model_id"],
        "forecast_model_ids": sorted(models),
        "research_release_plan_sha256": release["lineage"]["signed_plan_sha256"],
        "current_working_plan_sha256": before[plan],
        "software_sha256": fingerprint(source_files()),
        "study_database_sha256": before[database],
        "target_counts": counts,
        "topics": len(series),
        "selected_alpha": prediction["selected_alpha"],
        "comparison": data["forecast_comparison"],
        "local_explanations_replayed": sum(counts.values()),
        "global_explanation": prediction["global_explanation"],
        "fidelity": prediction["fidelity"],
        "stability": prediction["stability"],
        "projection_year": protocol.test_end + 1,
        "intervals": prediction["intervals"],
        "new_independent_holdout": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("store", "database", "plan", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.store, args.database, args.plan)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
    print(
        f"Replayed {result['local_explanations_replayed']} explanations "
        f"across {result['topics']} topics using release {result['release_id']}"
    )


if __name__ == "__main__":
    main()
