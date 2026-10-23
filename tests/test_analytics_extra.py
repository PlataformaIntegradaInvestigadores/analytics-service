import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.cli import main
from app.core.config import Settings
from app.data.snapshots import SnapshotStore
from app.domain.common import AnalyticsError
from app.main import create_app


def test_api_features_and_strict_lookbacks(series_request):
    client = TestClient(create_app(Settings(_env_file=None)))
    payload = {
        "series": series_request,
        "topic_id": "topic-a",
        "lags": [1],
        "rolling_windows": [2],
    }
    response = client.post("/api/v1/forecasts/features", json=payload)
    assert response.status_code == 200
    assert response.json()["rows"][-1]["features"] == {"lag_1": 6, "mean_2": 5.5}
    assert response.json()["rows"][-1]["target_value"] is None
    assert (
        client.post(
            "/api/v1/forecasts/features", json={**payload, "lags": [True]}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/forecasts/features", json={**payload, "lags": [1, 1]}
        ).json()["detail"]["code"]
        == "invalid_features"
    )


def test_shipped_synthetic_fixture_is_executable_via_cli(tmp_path, capsys):
    fixture = Path(__file__).parent / "fixtures" / "synthetic_series.json"
    assert main(["series", "--input", str(fixture)]) == 0
    series = json.loads(capsys.readouterr().out)
    assert series["data_kind"] == "synthetic"
    assert [
        p["count"] for p in series["points"] if p["topic_id"] == "synthetic-topic-a"
    ] == [1, 2, 1, 2, 0]
    assert series["topic_definition_version"].startswith("synthetic-")
    payload = {
        "series": json.loads(fixture.read_text(encoding="utf-8")),
        "topic_id": "synthetic-topic-a",
    }
    request = tmp_path / "request.json"
    for operation, options in (
        ("forecast", {"cutoff": "2020-04", "horizon": 2}),
        ("features", {"lags": [1], "rolling_windows": [2]}),
        (
            "backtest",
            {
                "validation_start": "2020-03",
                "validation_end": "2020-04",
                "final_test_start": "2020-05",
            },
        ),
    ):
        request.write_text(json.dumps({**payload, **options}), encoding="utf-8")
        assert main([operation, "--input", str(request)]) == 0
        result = json.loads(capsys.readouterr().out)
        assert result["series_version"] == series["series_version"]
    assert (
        main(
            [
                "restore",
                "--input",
                str(request),
                "--database",
                "unused",
                "--batch-id",
                "unused",
            ]
        )
        == 2
    )
    assert json.loads(capsys.readouterr().err)["error"] == "invalid_arguments"


@pytest.mark.parametrize("payload", ["{", "[]", "{}", '{"data_kind":"unknown"}'])
def test_malformed_snapshot_payloads_are_reported_as_corruption(
    tmp_path, record, payload
):
    store = SnapshotStore(tmp_path / "snapshots.sqlite")
    saved = store.save([record()], "synthetic")
    with sqlite3.connect(store.path) as connection:
        connection.execute("UPDATE batches SET result_payload = ?", (payload,))
    with pytest.raises(AnalyticsError) as error:
        store.load(saved["batch_id"])
    assert error.value.code == "snapshot_corrupt"
