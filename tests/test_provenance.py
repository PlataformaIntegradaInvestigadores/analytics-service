import json
from importlib.metadata import version

import pytest

from app.audit import main, replay_run
from app.core.provenance import (
    declared_dependencies,
    environment_manifest,
    software_inventory,
    source_files,
    verify_environment,
)
from app.data.forecast_runs import ForecastRunStore
from app.domain.common import AnalyticsError, fingerprint


@pytest.fixture
def project(tmp_path):
    (tmp_path / "app" / "domain").mkdir(parents=True)
    (tmp_path / "app" / "application").mkdir()
    (tmp_path / "app" / "main.py").write_text(
        "from app.domain import model\n", encoding="utf-8"
    )
    (tmp_path / "app" / "domain" / "model.py").write_text(
        "from dataclasses import dataclass\n", encoding="utf-8"
    )
    pin = f"pydantic=={version('pydantic')}\n"
    (tmp_path / "requirements.txt").write_text(
        "-c constraints.txt\n" + pin, encoding="utf-8"
    )
    (tmp_path / "requirements-dev.txt").write_text(
        "-r requirements.txt\n", encoding="utf-8"
    )
    (tmp_path / "constraints.txt").write_text(
        pin + "absent-constraint-package==1.0\n", encoding="utf-8"
    )
    (tmp_path / ".env").write_text(
        "SECRET=must-not-be-read-or-exported", encoding="utf-8"
    )
    return tmp_path


def test_real_environment_and_boundaries_are_verifiable_without_corpus():
    manifest = environment_manifest()
    assert manifest["status"] == "ok"
    assert manifest["dependency_mismatches"] == []
    assert verify_environment(manifest)["status"] == "ok"
    assert software_inventory()["boundary_violations"] == []
    assert "app/data/forecast_runs.py" in manifest["files_sha256"]


def test_manifest_detects_source_and_dependency_drift_and_excludes_secrets(project):
    manifest = environment_manifest(project)
    assert manifest == environment_manifest(project)
    assert manifest["status"] == "ok"
    assert "SECRET" not in json.dumps(manifest)
    assert ".env" not in manifest["files_sha256"]
    (project / "app/main.py").write_text("# changed implementation\n", encoding="utf-8")
    comparison = verify_environment(manifest, project)
    assert comparison["status"] == "mismatch"
    assert comparison["differences"] == ["files_sha256"]
    (project / "constraints.txt").write_text("pydantic==0.0.0\n", encoding="utf-8")
    with pytest.raises(AnalyticsError) as error:
        environment_manifest(project)
    assert error.value.code == "conflicting_pins"


def test_manifest_reports_missing_required_and_installed_version_mismatch(project):
    (project / "requirements.txt").write_text(
        "uninstalled-centinela-package==1.0\npydantic==0.0.0\n", encoding="utf-8"
    )
    result = environment_manifest(project)
    assert result["status"] == "mismatch"
    assert {item["package"] for item in result["dependency_mismatches"]} == {
        "pydantic",
        "uninstalled-centinela-package",
    }


@pytest.mark.parametrize("value", [None, [], {}, {"manifest_sha256": "wrong"}])
def test_invalid_manifest_is_rejected(project, value):
    with pytest.raises(AnalyticsError) as error:
        verify_environment(value, project)
    assert error.value.code == "invalid_environment_manifest"


def test_manifest_version_and_platform_comparison(project):
    expected = environment_manifest(project)
    expected["platform"] = {"system": "Other", "machine": "Other"}
    expected["manifest_sha256"] = fingerprint(
        {k: v for k, v in expected.items() if k != "manifest_sha256"}
    )
    comparison = verify_environment(expected, project)
    assert comparison["status"] == "ok" and comparison["platform_changed"]
    expected["manifest_version"] = "unsupported"
    expected["manifest_sha256"] = fingerprint(
        {k: v for k, v in expected.items() if k != "manifest_sha256"}
    )
    with pytest.raises(AnalyticsError):
        verify_environment(expected, project)


def test_manifest_missing_metadata_and_escaping_sources_are_rejected(
    project, monkeypatch
):
    expected = environment_manifest(project)
    del expected["platform"]
    expected["manifest_sha256"] = fingerprint(
        {k: v for k, v in expected.items() if k != "manifest_sha256"}
    )
    with pytest.raises(AnalyticsError) as error:
        verify_environment(expected, project)
    assert error.value.code == "invalid_environment_manifest"
    import app.core.provenance as provenance

    monkeypatch.setattr(provenance.Path, "is_relative_to", lambda *args: False)
    with pytest.raises(AnalyticsError) as error:
        source_files(project)
    assert error.value.code == "invalid_manifest_path"


@pytest.mark.parametrize(
    "content,code",
    [
        ("pydantic>=2\n", "unsupported_requirement"),
        ("-r requirements-dev.txt\n", "requirements_cycle"),
        ("pydantic==1\npydantic==2\n", "conflicting_pins"),
        ("-r missing.txt\n", "requirements_missing"),
        ("-r ../outside.txt\n", "invalid_manifest_path"),
    ],
)
def test_requirement_parser_refuses_ambiguous_or_external_inputs(
    project, content, code
):
    (project / "requirements-dev.txt").write_text(content, encoding="utf-8")
    with pytest.raises(AnalyticsError) as error:
        declared_dependencies(project, "requirements-dev.txt")
    assert error.value.code == code


def test_requirement_comments_shared_includes_and_name_normalization(project):
    (project / "requirements-dev.txt").write_text(
        "# comment\n-r requirements.txt\n-r requirements.txt\nCustom_Name==1.0 # pin\n",
        encoding="utf-8",
    )
    required, constraints = declared_dependencies(project, "requirements-dev.txt")
    assert required["custom-name"] == "1.0"
    assert constraints["absent-constraint-package"] == "1.0"
    assert "app/domain/model.py" in source_files(project)
    with pytest.raises(AnalyticsError):
        declared_dependencies(project, "../outside.txt")


def test_inventory_finds_boundary_violations_without_importing_modules(project):
    path = project / "app/domain/model.py"
    path.write_text(
        "import sqlite3\nfrom app.api import routes\nfrom . import sibling\n"
        "raise RuntimeError('must not execute')\n",
        encoding="utf-8",
    )
    inventory = software_inventory(project)
    assert inventory["status"] == "mismatch"
    assert {item["dependency"] for item in inventory["boundary_violations"]} == {
        "sqlite3",
        "app.api",
        ".",
    }


def test_application_allows_domain_but_not_similarly_named_adapter(project):
    path = project / "app/application/cases.py"
    path.write_text(
        "from app.domain import model\nfrom app.application import service\n"
        "import app.domain_adapter\n",
        encoding="utf-8",
    )
    inventory = software_inventory(project)
    assert [item["dependency"] for item in inventory["boundary_violations"]] == [
        "app.domain_adapter"
    ]


@pytest.fixture
def saved_run(tmp_path, series_request):
    database = tmp_path / "runs.sqlite"
    run = ForecastRunStore(database).save(
        {"series": series_request, "topic_id": "topic-a", "cutoff": "2020-05"}
    )
    return database, run


def test_reference_run_reexecution_and_drift_controls(saved_run, monkeypatch):
    database, run = saved_run
    result = replay_run(database, run["run_id"])
    assert result["status"] == "ok" and result["reexecuted"] and result["result_match"]
    monkeypatch.setattr("app.audit.sha256_file", lambda path: "different")
    result = replay_run(database, run["run_id"])
    assert result["status"] == "drift" and not result["reexecuted"]
    assert result["result_match"] is None


def test_reference_reexecution_distinguishes_mismatch_and_runtime_drift(
    saved_run, monkeypatch
):
    database, run = saved_run
    monkeypatch.setattr("app.audit.forecast_batch", lambda request: {"changed": True})
    assert replay_run(database, run["run_id"])["status"] == "result_mismatch"
    monkeypatch.setattr("app.audit.version", lambda name: "different")
    assert replay_run(database, run["run_id"])["status"] == "drift"


def test_audit_cli_actual_inventory_environment_schema_and_compare(tmp_path, capsys):
    assert main(["environment"]) == 0
    environment = json.loads(capsys.readouterr().out)
    path = tmp_path / "environment.json"
    path.write_text(json.dumps(environment), encoding="utf-8")
    assert main(["verify-environment", "--manifest", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["differences"] == []
    assert main(["inventory"]) == 0
    assert json.loads(capsys.readouterr().out)["modules"]
    assert main(["schema", "--public-base-path", "/api/analytics"]) == 0
    schema = json.loads(capsys.readouterr().out)
    assert schema["servers"] == [{"url": "/api/analytics"}]
    assert "/datasets/curate" in schema["paths"]
    assert main(["environment", "--requirements", "missing.txt"]) == 2
    assert json.loads(capsys.readouterr().err)["error"] == "requirements_missing"


def test_audit_cli_replay_and_exit_status(saved_run, capsys, monkeypatch):
    database, run = saved_run
    arguments = ["replay", "--database", str(database), "--run-id", run["run_id"]]
    assert main(arguments) == 0
    assert json.loads(capsys.readouterr().out)["result_match"]
    monkeypatch.setattr("app.audit.sha256_file", lambda path: "changed")
    assert main(arguments) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "drift"
    assert (
        main(
            ["verify-environment", "--manifest", str(database.parent / "missing.json")]
        )
        == 2
    )
    assert json.loads(capsys.readouterr().err)["error"] == "invalid_audit_input"
