"""Technical boundary checks. Empirical execution uses the private real corpus."""

import sqlite3

import httpx
import pyarrow as pa
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.core.provenance import sha256_file
from app.data.layers import LayerStore
from app.domain.common import AnalyticsError, canonical_json, fingerprint
from app.main import create_app


def table(rows=None):
    return {
        "silver_documents": {
            "layer": "silver",
            "schema": pa.schema([("document_id", pa.string()), ("year", pa.int64())]),
            "batches": [
                (
                    [{"document_id": "boundary-fixture", "year": 2020}]
                    if rows is None
                    else rows
                )
            ],
        }
    }


def test_atomic_bundle_replay_and_historical_reads(tmp_path):
    archive = LayerStore(tmp_path / "store", create=True)
    blob = tmp_path / "source.json"
    blob.write_text('{"scope":"technical fixture"}', encoding="utf8")
    blobs = {"protocol": {"layer": "silver", "path": blob}}
    a = archive.publish(table(), blobs, {"version": "unit-a"})
    repeated = archive.publish(table(), blobs, {"version": "unit-a"})
    assert repeated == a and len(archive.history()) == 1
    assert archive.read_table(a, "silver_documents")[0]["year"] == 2020
    assert archive.read_blob(a, "protocol") == blob.read_bytes()
    with pytest.raises(AnalyticsError, match="Head changed"):
        archive.publish(table(), blobs, {"version": "unit-b"})
    b = archive.publish(
        table([{"document_id": "new-fixture", "year": 2021}]),
        blobs,
        {"version": "unit-b"},
        expected_parent=a["release_id"],
    )
    assert b["parent"] == a["release_id"] and len(archive.history()) == 2
    assert archive.read_table(a, "silver_documents")[0]["year"] == 2020
    assert archive.verify()["status"] == "passed"
    assert archive.release()["release_id"] == b["release_id"]
    with pytest.raises(AnalyticsError):
        archive.release("../outside")
    with pytest.raises(AnalyticsError):
        archive.release("a" * 64)
    with pytest.raises(AnalyticsError):
        archive.read_blob(a, "not_in_release")


def test_failed_stream_or_changed_source_never_publishes_head(tmp_path):
    archive = LayerStore(tmp_path / "store", create=True)

    def fail():
        yield [{"document_id": "first", "year": 2020}]
        raise OSError("technical interrupted writer")

    spec = table()
    spec["silver_documents"]["batches"] = fail()
    with pytest.raises(OSError):
        archive.publish(spec, {}, {})
    assert archive.history() == []
    with pytest.raises(AnalyticsError):
        archive.release()
    source = tmp_path / "source.txt"
    source.write_text("new", encoding="utf8")
    with pytest.raises(AnalyticsError):
        archive.publish(table(), {}, {}, source_hashes={source: "0" * 64})
    assert archive.history() == []
    for invalid in ({}, {"../bad": table()["silver_documents"]}):
        with pytest.raises(AnalyticsError):
            archive.publish(invalid, {}, {})


def test_tampered_object_or_manifest_not_accepted(tmp_path):
    archive = LayerStore(tmp_path / "store", create=True)
    result = archive.publish(table(), {}, {})
    path = archive.object_path(result, "silver_documents", table=True)
    path.write_bytes(b"damaged technical fixture")
    with pytest.raises(AnalyticsError):
        archive.verify()
    with pytest.raises(AnalyticsError):
        archive.read_table(result, "silver_documents")
    with pytest.raises(AnalyticsError):
        archive.publish(table(), {}, {})
    with sqlite3.connect(archive.catalog) as db:
        db.execute("UPDATE releases SET payload='{}'")
    with pytest.raises(AnalyticsError):
        archive.release()
    with pytest.raises(AnalyticsError):
        LayerStore(tmp_path / "unknown")


def configured(**extra):
    return Settings(
        environment="staging",
        identity_allowed_users=["Allowed001"],
        identity_validation_url="http://identity-service:8002/internal/auth/validate-token/",
        **extra,
    )


@pytest.mark.parametrize(
    "status,principal,kind,expected",
    [
        (204, "Allowed001", "access", 200),
        (204, "Other00001", "access", 403),
        (204, "Allowed001", "refresh", 503),
        (204, "../path", "access", 503),
        (200, "Allowed001", "access", 503),
        (302, "Allowed001", "access", 503),
        (401, "", "", 401),
        (403, "", "", 403),
        (500, "", "", 503),
    ],
)
def test_identity_contract_deny_by_default(
    tmp_path, monkeypatch, status, principal, kind, expected
):
    original = httpx.Client
    seen = []

    def handle(request):
        seen.append(request)
        return httpx.Response(
            status,
            headers={
                "X-Authenticated-User-Id": principal,
                "X-Authenticated-Token-Type": kind,
            },
        )

    monkeypatch.setattr(
        "app.api.access.httpx.Client",
        lambda **kw: original(transport=httpx.MockTransport(handle), **kw),
    )
    archive = LayerStore(tmp_path / "store", create=True)
    result = archive.publish(table(), {}, {})
    with TestClient(create_app(configured(lake_directory=archive.root))) as client:
        response = client.get(
            "/api/v1/lineage/current",
            headers={
                "Authorization": "Bearer " + "x" * 30,
                "X-Authenticated-User-Id": "Allowed001",
            },
        )
        assert response.status_code == expected
        if expected == 200:
            assert response.json()["release_id"] == result["release_id"]
        else:
            assert "tables" not in response.json()
    assert len(seen) == 1
    assert seen[0].url.path == "/internal/auth/validate-token/"
    assert "x-authenticated-user-id" not in seen[0].headers


def test_missing_credentials_policy_and_network_failure(tmp_path, monkeypatch):
    settings = configured(lake_directory=tmp_path / "missing")
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/lineage/current").status_code == 401
        assert (
            client.get(
                "/api/v1/lineage/current",
                headers={"X-Authenticated-User-Id": "Allowed001"},
            ).status_code
            == 401
        )
        assert (
            client.post("/api/v1/corpus/preparation/preview", json={}).status_code
            == 403
        )
    settings.identity_allowed_users = []
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/lineage/current").status_code == 503
    original = httpx.Client

    def down(request):
        raise httpx.ConnectError("unavailable boundary fixture", request=request)

    monkeypatch.setattr(
        "app.api.access.httpx.Client",
        lambda **kw: original(transport=httpx.MockTransport(down), **kw),
    )
    with TestClient(create_app(configured())) as client:
        response = client.get(
            "/api/v1/lineage/current", headers={"Authorization": "Bearer " + "x" * 30}
        )
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "identity_unavailable"


def test_catalog_api_readonly_and_configuration(tmp_path):
    archive = LayerStore(tmp_path / "store", create=True)
    result = archive.publish(table(), {}, {})
    before = sha256_file(archive.catalog)
    with TestClient(create_app(Settings(lake_directory=archive.root))) as client:
        assert client.get("/api/v1/lineage/current").json() == result
        assert len(client.get("/api/v1/lineage/releases").json()["items"]) == 1
        assert (
            client.get("/api/v1/lineage/releases/" + result["release_id"]).status_code
            == 200
        )
        assert client.get("/api/v1/lineage/releases/" + "a" * 64).status_code == 404
        assert client.get("/api/v1/lineage/releases/invalid").status_code == 422
        assert client.post("/api/v1/lineage/current").status_code == 405
    assert sha256_file(archive.catalog) == before
    with TestClient(create_app(Settings())) as client:
        assert client.get("/api/v1/lineage/current").status_code == 503
    for url in [
        "http://outside.invalid/internal/auth/validate-token/",
        "https://a:bad/internal/auth/validate-token/",
        "https://a/wrong",
        "https://user:password@a/internal/auth/validate-token/",
        "https://a/internal/auth/validate-token/?credential=bad",
    ]:
        with pytest.raises(ValidationError):
            Settings(identity_validation_url=url)
    with pytest.raises(ValidationError):
        Settings(identity_allowed_users=["../invalid"])


def test_study_and_review_restore_from_versioned_gold(tmp_path):
    point = {"year": 2020, "count": 7}
    study = {
        "run_id": "unit-study",
        "identity": {"private": "omitted"},
        "protocol": {"approval_reference": "boundary fixture"},
        "preparation": {"source_year_counts": {}},
        "topics": [],
        "series": {"topic-0": [point]},
    }
    review = {"run_id": "unit-review", "identity": {"private": "omitted"}}
    blobs = {}
    for name, content in (("study_results", study), ("review_results", review)):
        path = tmp_path / (name + ".json")
        path.write_text(
            canonical_json({**content, "report_sha256": fingerprint(content)}),
            encoding="utf8",
        )
        blobs[name] = {"layer": "gold", "path": path}
    tables = {
        "gold_annual_series": {
            "layer": "gold",
            "schema": pa.schema(
                [("topic_id", pa.string()), ("year", pa.int64()), ("count", pa.int64())]
            ),
            "batches": [[{"topic_id": "topic-0", **point}]],
        }
    }
    archive = LayerStore(tmp_path / "store", create=True)
    lineage = {"study_run_id": "unit-study", "review_run_id": "unit-review"}
    published = archive.publish(tables, blobs, lineage)
    # The serving path uses immutable gold copies, not a changed source JSON.
    blobs["study_results"]["path"].write_text(
        "changed original fixture", encoding="utf8"
    )
    with TestClient(create_app(Settings(lake_directory=archive.root))) as client:
        result = client.get("/api/v1/study").json()
        assert (
            "identity" not in result and "approval_reference" not in result["protocol"]
        )
        assert result["series"] == study["series"]
        assert result["storage_lineage"]["release_id"] == published["release_id"]
        assert (
            client.get(
                "/api/v1/study", params={"release_id": published["release_id"]}
            ).json()
            == result
        )
        assert (
            client.get("/api/v1/study", params={"release_id": "f" * 64}).status_code
            == 404
        )
        assert (
            client.get("/api/v1/study", params={"release_id": "unknown"}).status_code
            == 422
        )
        assert client.get("/api/v1/study/review").json() == {"run_id": "unit-review"}


def test_sql_layer_preserves_empty_schema_and_integer_rows(tmp_path):
    from app.layer import _sql_table

    path = tmp_path / "input.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE records(id TEXT,year INTEGER)")
    archive = LayerStore(tmp_path / "store", create=True)
    result = archive.publish(
        {
            "silver_empty": _sql_table(
                path, "records", layer="silver", integers=("year",)
            )
        },
        {},
        {},
    )
    assert result["tables"]["silver_empty"]["rows"] == 0
    assert archive.read_table(result, "silver_empty") == []
    assert archive.verify()["status"] == "passed"
