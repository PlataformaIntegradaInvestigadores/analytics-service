import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.cli import main
from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def client():
    return TestClient(create_app(Settings(_env_file=None)))


def test_api_curation_split_series_forecast_backtest(client, batch, series_request):
    curated = client.post("/api/v1/datasets/curate", json=batch)
    assert curated.status_code == 200
    assert curated.json()["quality"]["accepted_documents"] == 1
    assert "X-Trace-ID" in curated.headers
    split = client.post(
        "/api/v1/datasets/split",
        json={
            "batch": batch,
            "train_end": "2020-01-31",
            "validation_end": "2020-02-29",
            "test_end": "2020-03-31",
        },
    )
    assert split.status_code == 200
    assert split.json()["partitions"]["train"] == ["doi:10.9999/synthetic-one"]
    series = client.post("/api/v1/series/build", json=series_request)
    assert series.status_code == 200
    payload = {"series": series_request, "topic_id": "topic-a"}
    forecast = client.post(
        "/api/v1/forecasts/reference", json={**payload, "cutoff": "2020-05"}
    )
    assert forecast.status_code == 200
    assert forecast.json()["predictions"][0] == {"period": "2020-06", "value": 5}
    backtest = client.post(
        "/api/v1/evaluations/backtest",
        json={
            **payload,
            "validation_start": "2020-03",
            "validation_end": "2020-05",
            "final_test_start": "2020-06",
        },
    )
    assert backtest.status_code == 200
    assert len(backtest.json()["folds"]) == 3
    assert backtest.json()["series_version"] == series.json()["series_version"]


def test_domain_errors_and_request_validation_have_explicit_responses(
    client, batch, series_request
):
    invalid = client.post(
        "/api/v1/datasets/split",
        json={
            "batch": batch,
            "train_end": "2020-03-31",
            "validation_end": "2020-02-29",
            "test_end": "2020-01-31",
        },
    )
    assert invalid.status_code == 422
    assert invalid.json()["detail"]["code"] == "invalid_cutoffs"
    assert "X-Trace-ID" in invalid.headers
    for payload in (
        {"records": []},
        {**batch, "extra": 1},
        {**batch, "data_kind": "unknown"},
        {**batch, "records": [{}] * 1001},
    ):
        assert client.post("/api/v1/datasets/curate", json=payload).status_code == 422
    wrong_bool = {
        "series": series_request,
        "topic_id": "topic-a",
        "cutoff": "2020-05",
        "horizon": True,
    }
    assert (
        client.post("/api/v1/forecasts/reference", json=wrong_bool).status_code == 422
    )
    assert (
        client.post(
            "/api/v1/series/build",
            json={**series_request, "assignments": {"missing": "topic-a"}},
        ).status_code
        == 422
    )


def test_api_insufficient_data_is_not_a_fabricated_prediction(client, series_request):
    series_request["covered_periods"].remove("2020-06")
    response = client.post(
        "/api/v1/forecasts/reference",
        json={"series": series_request, "topic_id": "topic-a", "cutoff": "2020-06"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "insufficient_data"
    assert response.json()["predictions"] == []


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_processing_is_disabled_until_remote_identity_integration(environment, batch):
    client = TestClient(create_app(Settings(_env_file=None, environment=environment)))
    response = client.post("/api/v1/datasets/curate", json=batch)
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "integration_pending"
    assert client.get("/health").status_code == 200
    assert client.get("/api/v1/status").status_code == 200


def test_openapi_documents_all_input_and_output_contracts(client):
    schema = client.get("/openapi.json").json()
    expected = {
        "/datasets/curate",
        "/datasets/split",
        "/series/build",
        "/forecasts/reference",
        "/evaluations/backtest",
        "/forecasts/features",
    }
    assert expected < set(schema["paths"])
    for path in expected:
        operation = schema["paths"][path]["post"]
        assert operation["responses"]["422"]["content"]["application/json"]["schema"][
            "$ref"
        ].endswith("ErrorResponse")
        assert operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        assert operation["responses"]["200"]["content"]["application/json"]["schema"][
            "$ref"
        ]


def test_cli_roundtrip_in_database_and_error_responses(tmp_path, batch, capsys):
    request = tmp_path / "batch.json"
    database = tmp_path / "snapshots.sqlite"
    request.write_text(json.dumps(batch), encoding="utf-8")
    assert main(["curate", "--input", str(request), "--database", str(database)]) == 0
    saved = json.loads(capsys.readouterr().out)
    assert saved["result"]["data_kind"] == "synthetic"
    assert (
        main(["restore", "--database", str(database), "--batch-id", saved["batch_id"]])
        == 0
    )
    assert json.loads(capsys.readouterr().out) == saved
    assert main(["curate", "--input", str(request)]) == 0
    assert json.loads(capsys.readouterr().out) == saved["result"]
    assert (
        main(
            [
                "restore",
                "--database",
                str(tmp_path / "missing.sqlite"),
                "--batch-id",
                "missing",
            ]
        )
        == 2
    )
    assert json.loads(capsys.readouterr().err)["error"] == "snapshot_not_found"
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM batches").fetchone()[0] == 1


@pytest.mark.parametrize(
    "arguments",
    [
        ["curate"],
        ["restore"],
        ["curate", "--input", "missing.json"],
        ["curate", "--input", "missing.json", "--batch-id", "not-allowed"],
    ],
)
def test_cli_argument_and_file_errors(arguments, capsys):
    assert main(arguments) == 2
    assert json.loads(capsys.readouterr().err)["error"]


def test_cli_validates_json_and_database_operation_scope(tmp_path, batch, capsys):
    request = tmp_path / "request.json"
    request.write_text("{}", encoding="utf-8")
    assert main(["curate", "--input", str(request)]) == 2
    assert json.loads(capsys.readouterr().err)["error"] == "invalid_input"
    request.write_text(
        json.dumps(
            {
                "batch": batch,
                "train_end": "2020-01-31",
                "validation_end": "2020-02-29",
                "test_end": "2020-03-31",
            }
        ),
        encoding="utf-8",
    )
    assert (
        main(
            [
                "split",
                "--input",
                str(request),
                "--database",
                str(tmp_path / "db.sqlite"),
            ]
        )
        == 2
    )
    assert json.loads(capsys.readouterr().err)["error"] == "invalid_arguments"
    assert main(["split", "--input", str(request)]) == 0
    assert json.loads(capsys.readouterr().out)["partitions"]["train"]
