"""Persistence, lineage, presentation, CLI and API contracts on synthetic inputs."""

import json
import sqlite3
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from app.application.presentation import dashboard_view, explanation_state
from app.cli import main as analytical_cli
from app.core.config import Settings
from app.data.experiments import KINDS, ExperimentStore, _restore
from app.domain.common import AnalyticsError, canonical_json, fingerprint
from app.experiments import main
from app.main import create_app
from app.schemas.workflow import DashboardView


@pytest.fixture
def experiment_request(series_request):
    return {
        "kind": "reference_forecast",
        "request": {
            "series": series_request,
            "topic_id": "topic-a",
            "cutoff": "2020-05",
            "horizon": 2,
        },
    }


@pytest.fixture
def database(tmp_path):
    return ExperimentStore(tmp_path / "artifacts.sqlite")


@pytest.fixture
def client(tmp_path):
    return TestClient(
        create_app(
            Settings(_env_file=None, artifact_database=tmp_path / "artifacts.sqlite")
        )
    )


def test_experiment_roundtrip_idempotence_and_readonly_queries(
    database, experiment_request
):
    assert database.query()["status"] == "empty"
    assert not database.path.exists()
    saved = database.save(experiment_request)
    assert saved["software"]["entry"] == "requirements.txt"
    assert database.save(experiment_request) == saved
    assert database.load(saved["experiment_id"]) == saved
    before = database.path.read_bytes()
    page = database.query(
        limit=1,
        kind="reference_forecast",
        data_kind="synthetic",
        topic_id="topic-a",
        status="ok",
    )
    assert page["total"] == 1
    assert page["items"][0]["experiment_id"] == saved["experiment_id"]
    assert database.query(offset=1)["status"] == "empty"
    assert database.query(topic_id="x' OR 1=1 --")["total"] == 0
    assert database.path.read_bytes() == before


def test_lineage_requires_dataset_and_catalog_definition(database, experiment_request):
    series = experiment_request["request"]["series"]
    catalog = database.save(
        {
            "kind": "topic_catalog",
            "request": {
                "batch": series["batch"],
                "topics": [
                    {"topic_id": topic, "label": topic, "terms": [topic]}
                    for topic in series["topic_ids"]
                ],
                "assignments": series["assignments"],
                "method": "manual",
            },
        }
    )
    experiment_request["parent_ids"] = [catalog["experiment_id"]]
    with pytest.raises(AnalyticsError, match="parent catalog thematic"):
        database.save(experiment_request)
    series["topic_definition_version"] = catalog["result"]["topic_definition_version"]
    forecast = database.save(experiment_request)
    assert forecast["parent_ids"] == [catalog["experiment_id"]]
    comparison = database.save(
        {
            "kind": "reference_comparison",
            "parent_ids": [forecast["experiment_id"]],
            "request": {
                "series": series,
                "topic_id": "topic-a",
                "validation_start": "2020-03",
                "validation_end": "2020-05",
                "final_test_start": "2020-06",
                "season_length": 2,
            },
        }
    )
    assert comparison["result"]["status"] == "ok"
    other = deepcopy(experiment_request)
    other["request"]["series"]["batch"]["data_kind"] = "empirical"
    with pytest.raises(AnalyticsError, match="identical dataset"):
        database.save(other)
    other = deepcopy(experiment_request)
    other["parent_ids"] *= 2
    with pytest.raises(AnalyticsError, match="must be unique"):
        database.save(other)
    assert database.query()["total"] == 3


def test_unknown_parent_rolls_back_first_write(database, experiment_request):
    with pytest.raises(AnalyticsError, match="Unknown experiment"):
        database.save({**experiment_request, "parent_ids": ["not-found"]})
    assert database.query()["total"] == 0
    assert database.save(experiment_request)


@pytest.mark.parametrize(
    "options",
    [
        {"limit": 0},
        {"limit": True},
        {"offset": -1},
        {"offset": False},
        {"limit": "1"},
        {"offset": "1"},
        {"limit": 101},
        {"offset": 1000001},
        {"unknown": "x"},
        {"kind": "invalid"},
        {"data_kind": "fake"},
        {"topic_id": " "},
        {"topic_id": []},
        {"status": "x"},
    ],
)
def test_query_rejects_invalid_arguments(database, options):
    with pytest.raises(AnalyticsError):
        database.query(**options)


def test_unknown_database_table_or_identifier(database, experiment_request):
    with pytest.raises(AnalyticsError, match="No experiment database"):
        database.load("missing")
    assert not database.path.exists()
    with sqlite3.connect(database.path) as connection:
        connection.execute("CREATE TABLE unrelated (id TEXT)")
    assert database.query()["status"] == "empty"
    with pytest.raises(AnalyticsError, match="No saved experiments"):
        database.load("missing")
    database.save(experiment_request)
    with pytest.raises(AnalyticsError, match="Unknown experiment"):
        database.load("missing")


def test_content_corruption_is_not_repaired(database, experiment_request):
    saved = database.save(experiment_request)
    with sqlite3.connect(database.path) as connection:
        connection.execute("UPDATE experiments SET payload='{}'")
    for operation in (
        lambda: database.load(saved["experiment_id"]),
        lambda: database.query(),
        lambda: database.save(experiment_request),
    ):
        with pytest.raises(AnalyticsError) as exc:
            operation()
        assert exc.value.code == "experiment_corrupt"


def test_index_corruption_detected_on_read_and_write(database, experiment_request):
    saved = database.save(experiment_request)
    with sqlite3.connect(database.path) as connection:
        connection.execute("UPDATE experiments SET status='insufficient_data'")
    for operation in (
        lambda: database.load(saved["experiment_id"]),
        lambda: database.query(),
        lambda: database.save(experiment_request),
    ):
        with pytest.raises(AnalyticsError, match="index disagrees"):
            operation()


def test_trigger_failure_rolls_back_without_partial_experiment(
    database, experiment_request
):
    first = database.save(experiment_request)
    with sqlite3.connect(database.path) as connection:
        connection.execute(
            "CREATE TRIGGER break_insert AFTER INSERT ON experiments BEGIN "
            "UPDATE experiments SET payload='{}' "
            "WHERE experiment_id=NEW.experiment_id; END"
        )
    experiment_request["request"]["horizon"] = 3
    with pytest.raises(AnalyticsError, match="identity or contracts"):
        database.save(experiment_request)
    assert database.query()["total"] == 1
    assert database.load(first["experiment_id"]) == first


@pytest.mark.parametrize(
    "change",
    [
        lambda x: x.update(artifact_version="future"),
        lambda x: x["request"].update(horizon=True),
        lambda x: x["result"].update(data_kind="empirical"),
        lambda x: x["result"].update(topic_id="other"),
        lambda x: x["result"].update(cutoff="2020-04"),
        lambda x: x["software"].update(python="modified"),
        lambda x: x.update(parent_ids=["same", "same"]),
        lambda x: x["request"].pop("season_length"),
    ],
)
def test_restoration_checks_envelope_and_contract_bindings(
    database, experiment_request, change
):
    saved = database.save(experiment_request)
    content = {key: value for key, value in saved.items() if key != "experiment_id"}
    change(content)
    with pytest.raises(AnalyticsError, match="identity or contracts"):
        _restore(canonical_json(content), fingerprint(content))


@pytest.mark.parametrize(
    "content",
    [None, "not-json", "[]", " " * (8 * 1024 * 1024 + 1)],
    ids=["not-text", "invalid-json", "not-object", "oversized"],
)
def test_restore_malformed_data_is_controlled(content):
    with pytest.raises(AnalyticsError, match="identity or contracts"):
        _restore(content, "missing")


def test_dashboard_and_xai_preserve_provenance_without_fabrication(
    database, experiment_request
):
    saved = database.save(experiment_request)
    view = DashboardView.model_validate(dashboard_view(saved)).model_dump()
    assert all(point["period"] <= view["cutoff"] for point in view["observed"])
    assert all(point["period"] > view["cutoff"] for point in view["forecast"])
    assert view["forecast"] == saved["result"]["predictions"]
    assert view["explanation"]["attributions"] == []
    assert view["explanation"]["method"] is None
    assert view["explanation"]["status"] == "pending"
    assert explanation_state(saved, "global")["scope"] == "global"
    assert dashboard_view(saved, "2021-01", "2021-02")["status"] == "empty"
    assert len(dashboard_view(saved, "2020-04", "2020-06")["observed"]) == 2
    with pytest.raises(AnalyticsError, match="Start must"):
        dashboard_view(saved, "2021-01", "2020-01")
    with pytest.raises(AnalyticsError, match="complete YYYY"):
        dashboard_view(saved, "bad")
    with pytest.raises(AnalyticsError, match="local or global"):
        explanation_state(saved, "unknown")
    changed = deepcopy(saved)
    changed["result"]["series_version"] = "changed"
    with pytest.raises(AnalyticsError, match="differs from the saved"):
        dashboard_view(changed)
    with pytest.raises(AnalyticsError, match="saved reference forecast"):
        explanation_state({**saved, "kind": "topic_catalog"})


def test_insufficient_forecasts_and_null_observations_remain_explicit(
    database, experiment_request
):
    experiment_request["request"]["series"]["covered_periods"].remove("2020-05")
    saved = database.save(experiment_request)
    view = dashboard_view(saved)
    assert view["status"] == "insufficient_data"
    assert view["forecast"] == []
    assert view["observed"][-1]["count"] is None
    assert view["explanation"]["status"] == "unavailable"
    assert view["explanation"]["reason"] == "forecast_insufficient_data"
    assert database.query(status="insufficient_data")["total"] == 1


def test_workflow_api_save_list_presentation_and_errors(client, experiment_request):
    assert client.get("/api/v1/experiments").json()["status"] == "empty"
    response = client.post("/api/v1/experiments", json=experiment_request)
    assert response.status_code == 200
    artifact = response.json()
    identifier = artifact["experiment_id"]
    assert "X-Trace-ID" in response.headers
    assert client.get(f"/api/v1/experiments/{identifier}").json() == artifact
    assert (
        client.get(
            "/api/v1/experiments?data_kind=synthetic&topic_id=topic-a&limit=1"
        ).json()["total"]
        == 1
    )
    assert (
        client.get(f"/api/v1/experiments/{identifier}/explanation?scope=global").json()[
            "status"
        ]
        == "pending"
    )
    assert (
        client.get(f"/api/v1/experiments/{identifier}/dashboard?start=2020-06").json()[
            "observed"
        ]
        == []
    )
    assert client.get("/api/v1/experiments/missing").status_code == 404
    assert (
        client.get(f"/api/v1/experiments/{identifier}/dashboard?start=bad").status_code
        == 422
    )
    assert client.get("/api/v1/experiments?limit=101").status_code == 422
    assert client.get("/api/v1/experiments?kind=anything").status_code == 422
    assert (
        client.post(
            "/api/v1/experiments", json={"kind": "reference_forecast", "request": {}}
        ).status_code
        == 422
    )
    assert client.get("/api/v1/datasets/dictionary").json()["limits"]["rows"] == 1000
    assert (
        client.get("/api/v1/dashboard/contract").json()["granularity"]
        == "calendar_month"
    )


def test_workflow_api_configuration_corruption_and_remote_guard(
    tmp_path, experiment_request
):
    plain = TestClient(create_app(Settings(_env_file=None)))
    assert (
        plain.get("/api/v1/experiments").json()["detail"]["code"]
        == "artifact_store_unconfigured"
    )
    corrupt = tmp_path / "corrupt.sqlite"
    corrupt.write_text("not sqlite", encoding="utf-8")
    client = TestClient(create_app(Settings(_env_file=None, artifact_database=corrupt)))
    response = client.get("/api/v1/experiments")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "artifact_storage_unavailable"
    for environment in ("staging", "production"):
        client = TestClient(
            create_app(Settings(_env_file=None, environment=environment))
        )
        assert client.get("/api/v1/dashboard/contract").status_code == 503
        assert (
            client.post("/api/v1/experiments", json=experiment_request).status_code
            == 503
        )
    path = tmp_path / "store.sqlite"
    saved = ExperimentStore(path).save(experiment_request)
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE experiments SET payload='{}'")
    client = TestClient(create_app(Settings(_env_file=None, artifact_database=path)))
    assert (
        client.get(f"/api/v1/experiments/{saved['experiment_id']}").status_code == 422
    )


def test_topics_comparison_api_and_new_analytical_cli(
    client, series_request, tmp_path, capsys
):
    catalog = {
        "batch": series_request["batch"],
        "topics": [
            {"topic_id": topic, "label": topic, "terms": [topic]}
            for topic in series_request["topic_ids"]
        ],
        "assignments": series_request["assignments"],
        "method": "manual",
    }
    catalog_series = {
        "catalog": catalog,
        "start": series_request["start"],
        "end": series_request["end"],
        "covered_periods": series_request["covered_periods"],
    }
    comparison = {
        "series": series_request,
        "topic_id": "topic-a",
        "validation_start": "2020-03",
        "validation_end": "2020-05",
        "final_test_start": "2020-06",
        "season_length": 2,
    }
    for operation, route, payload in (
        ("catalog", "/topics/catalog", catalog),
        ("catalog-series", "/series/from-catalog", catalog_series),
        ("compare", "/evaluations/compare", comparison),
    ):
        response = client.post("/api/v1" + route, json=payload)
        assert response.status_code == 200, response.text
        request = tmp_path / "request.json"
        request.write_text(json.dumps(payload), encoding="utf-8")
        assert analytical_cli([operation, "--input", str(request)]) == 0
        assert json.loads(capsys.readouterr().out) == response.json()
    saved = client.post(
        "/api/v1/experiments", json={"kind": "topic_catalog", "request": catalog}
    ).json()
    assert (
        client.get(
            f"/api/v1/experiments/{saved['experiment_id']}/explanation"
        ).status_code
        == 422
    )


def test_experiment_cli_roundtrip_and_errors(tmp_path, experiment_request, capsys):
    database = str(tmp_path / "artifacts.sqlite")
    path = tmp_path / "request.json"
    path.write_text(json.dumps(experiment_request), encoding="utf-8")
    assert main(["save", "--database", database, "--input", str(path)]) == 0
    saved = json.loads(capsys.readouterr().out)
    for operation in ("show", "dashboard", "explanation"):
        assert (
            main([operation, "--database", database, "--id", saved["experiment_id"]])
            == 0
        )
        value = json.loads(capsys.readouterr().out)
        assert value["experiment_id"] == saved["experiment_id"]
    assert main(["list", "--database", database, "--kind", "reference_forecast"]) == 0
    assert json.loads(capsys.readouterr().out)["total"] == 1
    assert main(["show", "--database", database, "--id", "missing"]) == 2
    assert json.loads(capsys.readouterr().err)["error"] == "experiment_not_found"
    path.write_text("{}", encoding="utf-8")
    assert main(["save", "--database", database, "--input", str(path)]) == 2
    assert json.loads(capsys.readouterr().err)["error"] == "invalid_input"


def test_openapi_has_workflow_requests_responses_and_base_path(client):
    schema = client.get("/openapi.json").json()
    assert schema["servers"] == [{"url": "/api/v1"}]
    for path in (
        "/experiments",
        "/topics/catalog",
        "/series/from-catalog",
        "/evaluations/compare",
    ):
        operation = schema["paths"][path]["post"]
        assert operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        assert operation["responses"]["200"]["content"]["application/json"]["schema"][
            "$ref"
        ]
    assert schema["paths"]["/experiments/{identifier}"]["get"]["responses"]["404"]


def test_experiment_replay_checks_software_and_results(
    database, experiment_request, monkeypatch
):
    saved = database.save(experiment_request)
    identifier = saved["experiment_id"]
    before = database.path.read_bytes()
    replay = database.replay(identifier)
    assert replay["status"] == "ok"
    assert replay["recomputed"] is True
    assert replay["result_sha256"] == replay["expected_sha256"]
    assert database.path.read_bytes() == before
    monkeypatch.setattr(
        "app.data.experiments.verify_environment",
        lambda manifest: {"status": "mismatch"},
    )
    replay = database.replay(identifier)
    assert replay["reason"] == "software_drift"
    assert replay["recomputed"] is False
    monkeypatch.setattr(
        "app.data.experiments.verify_environment", lambda manifest: {"status": "ok"}
    )
    schema, result_schema, operation = KINDS["reference_forecast"]

    def changed(request):
        result = operation(request)
        result["reason"] = "test_injected_mismatch"
        return result

    monkeypatch.setitem(
        KINDS,
        "reference_forecast",
        (schema, result_schema, changed),
    )
    assert database.replay(identifier)["reason"] == "result_mismatch"


def test_cli_replay_exit_codes(tmp_path, experiment_request, capsys, monkeypatch):
    store = ExperimentStore(tmp_path / "saved.sqlite")
    saved = store.save(experiment_request)
    args = ["replay", "--database", str(store.path), "--id", saved["experiment_id"]]
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "ok"
    monkeypatch.setattr(
        "app.data.experiments.verify_environment",
        lambda manifest: {"status": "mismatch"},
    )
    assert main(args) == 1
    assert json.loads(capsys.readouterr().out)["recomputed"] is False


def test_dashboard_refuses_to_mix_new_software_with_saved_results(
    database, experiment_request, monkeypatch
):
    saved = database.save(experiment_request)
    identifier = saved["experiment_id"]
    assert database.dashboard(identifier)["status"] == "ready"
    monkeypatch.setattr(
        "app.data.experiments.verify_environment",
        lambda manifest: {"status": "mismatch"},
    )
    with pytest.raises(AnalyticsError) as exc:
        database.dashboard(identifier)
    assert exc.value.code == "experiment_software_drift"
    assert database.load(identifier) == saved


def test_dashboard_api_reports_software_drift(client, experiment_request, monkeypatch):
    saved = client.post("/api/v1/experiments", json=experiment_request).json()
    monkeypatch.setattr(
        "app.data.experiments.verify_environment",
        lambda manifest: {"status": "mismatch"},
    )
    response = client.get(f"/api/v1/experiments/{saved['experiment_id']}/dashboard")
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "experiment_software_drift"
