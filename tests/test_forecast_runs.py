import json
import sqlite3

import pytest

from app.application.analysis import forecast_batch
from app.cli import main
from app.data.forecast_runs import ARTIFACT_VERSION, SOURCE_FILES, ForecastRunStore
from app.data.snapshots import SnapshotStore
from app.domain.common import AnalyticsError, canonical_json, fingerprint
from app.schemas.analytics import ForecastRequest


@pytest.fixture
def forecast_request(series_request):
    return {
        "series": series_request,
        "topic_id": "topic-a",
        "cutoff": "2020-05",
        "horizon": 2,
    }


def test_forecast_runs_preserve_inputs_outputs_versions_and_runtime(
    tmp_path, forecast_request
):
    store = ForecastRunStore(tmp_path / "runs.sqlite")
    saved = store.save(forecast_request)
    request = ForecastRequest.model_validate(forecast_request).model_dump(mode="json")
    assert saved["request"] == request
    assert saved["result"] == forecast_batch(request)
    assert saved["result"]["data_kind"] == "synthetic"
    assert saved["result"]["predictions"] == [
        {"period": "2020-06", "value": 5.0},
        {"period": "2020-07", "value": 5.0},
    ]
    assert saved["artifact_version"] == ARTIFACT_VERSION
    assert set(saved["runtime"]) == {"python", "service", "pydantic"}
    assert all(saved["runtime"].values())
    assert set(saved["code_sha256"]) == set(SOURCE_FILES)
    assert all(len(value) == 64 for value in saved["code_sha256"].values())
    assert store.save(forecast_request) == saved
    original_bytes = store.path.read_bytes()
    assert store.load(saved["run_id"]) == saved
    assert store.path.read_bytes() == original_bytes
    revised = store.save({**forecast_request, "horizon": 1})
    assert revised["run_id"] != saved["run_id"]
    assert store.load(saved["run_id"]) == saved
    with sqlite3.connect(store.path) as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM forecast_runs").fetchone()[0] == 2
        )


def test_forecast_and_dataset_snapshots_coexist(tmp_path, forecast_request):
    path = tmp_path / "artifacts.sqlite"
    batches = SnapshotStore(path)
    batch = batches.save(**forecast_request["series"]["batch"])
    runs = ForecastRunStore(path)
    saved = runs.save(forecast_request)
    assert batches.load(batch["batch_id"]) == batch
    assert saved["result"]["dataset_version"] == batch["dataset_version"]
    assert runs.load(saved["run_id"]) == saved


def test_insufficient_forecast_is_preserved_without_inventing_predictions(
    tmp_path, forecast_request
):
    forecast_request["series"]["covered_periods"].remove("2020-05")
    store = ForecastRunStore(tmp_path / "runs.sqlite")
    saved = store.save(forecast_request)
    assert saved["result"]["status"] == "insufficient_data"
    assert saved["result"]["predictions"] == []
    assert saved["result"]["reason"] == "missing_required_history"
    assert store.load(saved["run_id"]) == saved


def test_restore_never_reexecutes_forecast_or_replaces_recorded_runtime(
    tmp_path, forecast_request, monkeypatch
):
    store = ForecastRunStore(tmp_path / "runs.sqlite")
    saved = store.save(forecast_request)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("Restoration must not rerun inference")

    monkeypatch.setattr("app.data.forecast_runs.forecast_batch", fail_if_called)
    monkeypatch.setattr("app.data.forecast_runs.version", fail_if_called)
    assert store.load(saved["run_id"]) == saved


def test_environment_changes_produce_distinct_runs(
    tmp_path, forecast_request, monkeypatch
):
    store = ForecastRunStore(tmp_path / "runs.sqlite")
    original = store.save(forecast_request)
    monkeypatch.setattr(
        "app.data.forecast_runs.version", lambda name: "test-alternate-version"
    )
    revised = store.save(forecast_request)
    assert revised["result"] == original["result"]
    assert revised["run_id"] != original["run_id"]
    assert store.load(original["run_id"]) == original


@pytest.mark.parametrize("payload", ["{", "[]", "null", "{}"])
def test_corruption_does_not_get_overwritten(tmp_path, forecast_request, payload):
    store = ForecastRunStore(tmp_path / "runs.sqlite")
    saved = store.save(forecast_request)
    with sqlite3.connect(store.path) as connection:
        connection.execute("UPDATE forecast_runs SET payload = ?", (payload,))
    for operation in (
        lambda: store.load(saved["run_id"]),
        lambda: store.save(forecast_request),
    ):
        with pytest.raises(AnalyticsError) as error:
            operation()
        assert error.value.code == "forecast_run_corrupt"
    with sqlite3.connect(store.path) as connection:
        assert (
            connection.execute("SELECT payload FROM forecast_runs").fetchone()[0]
            == payload
        )


@pytest.mark.parametrize(
    "change,expected_code",
    [
        (
            lambda artifact: artifact.update(artifact_version="future-v2"),
            "unsupported_artifact_version",
        ),
        (
            lambda artifact: artifact.update(artifact_kind="other"),
            "forecast_run_corrupt",
        ),
        (lambda artifact: artifact.update(extra="unsupported"), "forecast_run_corrupt"),
        (lambda artifact: artifact["request"].pop("horizon"), "forecast_run_corrupt"),
        (
            lambda artifact: artifact["result"].update(topic_id="different"),
            "forecast_run_corrupt",
        ),
        (
            lambda artifact: artifact["result"].update(predictions="invalid"),
            "forecast_run_corrupt",
        ),
    ],
)
def test_restored_artifact_format_contracts_and_lineage(
    tmp_path, forecast_request, change, expected_code
):
    store = ForecastRunStore(tmp_path / "runs.sqlite")
    saved = store.save(forecast_request)
    artifact = {key: value for key, value in saved.items() if key != "run_id"}
    change(artifact)
    revised_id = fingerprint(artifact)
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            "INSERT INTO forecast_runs VALUES (?, ?)",
            (revised_id, canonical_json(artifact)),
        )
    with pytest.raises(AnalyticsError) as error:
        store.load(revised_id)
    assert error.value.code == expected_code


def test_missing_run_and_database_are_read_only(tmp_path, forecast_request):
    path = tmp_path / "runs.sqlite"
    store = ForecastRunStore(path)
    with pytest.raises(AnalyticsError, match="does not exist"):
        store.load("missing")
    assert not path.exists()
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE unrelated (id INTEGER)")
    with pytest.raises(AnalyticsError, match="No reference runs"):
        store.load("missing")
    store.save(forecast_request)
    with pytest.raises(AnalyticsError, match="Unknown run"):
        store.load("' OR 1=1 --")


def test_cli_persists_and_restores_forecast(tmp_path, forecast_request, capsys):
    path = tmp_path / "runs.sqlite"
    request = tmp_path / "request.json"
    request.write_text(json.dumps(forecast_request), encoding="utf-8")
    assert main(["forecast", "--input", str(request), "--database", str(path)]) == 0
    saved = json.loads(capsys.readouterr().out)
    assert saved["result"]["data_kind"] == "synthetic"
    assert (
        main(["restore-forecast", "--database", str(path), "--run-id", saved["run_id"]])
        == 0
    )
    assert json.loads(capsys.readouterr().out) == saved
    assert main(["forecast", "--input", str(request)]) == 0
    assert json.loads(capsys.readouterr().out) == saved["result"]


@pytest.mark.parametrize(
    "arguments",
    [
        ["restore-forecast"],
        ["restore-forecast", "--database", "unused", "--batch-id", "wrong"],
        [
            "restore-forecast",
            "--database",
            "unused",
            "--run-id",
            "missing",
            "--input",
            "unused",
        ],
        [
            "restore",
            "--database",
            "unused",
            "--batch-id",
            "missing",
            "--run-id",
            "wrong",
        ],
        ["forecast", "--input", "unused", "--run-id", "wrong"],
    ],
)
def test_cli_rejects_ambiguous_restore_arguments(arguments, capsys):
    assert main(arguments) == 2
    assert json.loads(capsys.readouterr().err)["error"] == "invalid_arguments"
