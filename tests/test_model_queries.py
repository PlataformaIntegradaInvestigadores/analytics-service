import hashlib
import sqlite3
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from app.application.modeling import fit_nmf
from app.core.config import Settings
from app.data.model_queries import model_detail, model_page, summary
from app.data.models import ModelStore
from app.domain.common import AnalyticsError, canonical_json, fingerprint
from app.main import create_app


@pytest.fixture
def registry(tmp_path):
    path = tmp_path / "models.sqlite"
    docs = [
        {"document_id": str(i), "text": text}
        for i, text in enumerate(
            [
                "solar sunlight energy panel",
                "solar energy renewable panel",
                "machine neural learning model",
                "neural network model learning",
            ]
        )
    ]
    model = fit_nmf(docs, ["0", "1", "2", "3"], workset_id="a" * 64)
    ModelStore(path).save(model)
    return path, model


def test_metadata_http_and_read_only(registry):
    path, model = registry
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    with TestClient(create_app(Settings(model_database=path))) as client:
        page = client.get("/api/v1/models").json()
        assert page["total"] == 1
        detail = client.get("/api/v1/models/" + model["model_id"])
        assert detail.status_code == 200
        assert detail.json() == page["items"][0]
        assert detail.json()["evaluation_status"] == "not_research_validated"
        assert detail.json()["fit_document_count"] == 4
        assert (
            not {"fit_ids", "vocabulary", "idf", "components", "software_sha256"}
            & detail.json().keys()
        )
        assert client.get("/api/v1/models?offset=1").json()["status"] == "empty"
        assert client.get("/api/v1/models/" + "f" * 64).status_code == 404
        assert client.get("/api/v1/models/invalid").status_code == 422
        for query in ("limit=0", "limit=101", "offset=-1", "offset=1000001"):
            assert client.get("/api/v1/models?" + query).status_code == 422
    assert before == hashlib.sha256(path.read_bytes()).hexdigest()


def test_page_boundaries_order_and_empty(registry, tmp_path):
    path, model = registry
    store = ModelStore(path)
    for i in range(23):
        content = {k: v for k, v in model.items() if k != "model_id"}
        content["workset_id"] = f"{i:064x}"
        store.save({"model_id": fingerprint(content), **content})
    first, second = model_page(path), model_page(path, 20, 20)
    ids = [m["model_id"] for m in first["items"] + second["items"]]
    assert len(ids) == 24 == len(set(ids))
    assert ids == sorted(ids)
    with pytest.raises(AnalyticsError):
        model_page(path, limit=0)
    empty = tmp_path / "empty.sqlite"
    ModelStore(empty)
    assert model_page(empty)["status"] == "empty"


def test_missing_registry_is_not_created(tmp_path):
    absent = tmp_path / "absent.sqlite"
    for settings in (Settings(), Settings(model_database=absent)):
        with TestClient(create_app(settings)) as client:
            assert client.get("/api/v1/models").status_code == 503
    assert not absent.exists()
    with pytest.raises(AnalyticsError):
        model_detail(absent, "a" * 64)


def test_corrupt_registry_never_exposes_payload(registry):
    path, model = registry
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("UPDATE fitted_models SET payload=?", ('{"private":"not-public"}',))
    with TestClient(create_app(Settings(model_database=path))) as client:
        for url in ("/api/v1/models", "/api/v1/models/" + model["model_id"]):
            response = client.get(url)
            assert response.status_code == 409
            assert response.json()["detail"]["code"] == "model_integrity"
            assert "not-public" not in response.text


@pytest.mark.parametrize("mutate", ["format", "purpose", "duplicate", "missing"])
def test_hash_alone_does_not_prove_valid_metadata(registry, mutate):
    _, model = registry
    content = {k: v for k, v in model.items() if k != "model_id"}
    if mutate == "format":
        content["format"] = "unknown"
    elif mutate == "purpose":
        content["purpose"] = "research"
    elif mutate == "duplicate":
        content["fit_ids"] = ["0", "0"]
    else:
        del content["configuration"]
    with pytest.raises(AnalyticsError):
        summary(fingerprint(content), canonical_json(content))


def test_production_guard_and_bad_schema(tmp_path, registry):
    path, _ = registry
    with TestClient(
        create_app(Settings(environment="production", model_database=path))
    ) as client:
        response = client.get("/api/v1/models")
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "integration_pending"
    wrong = tmp_path / "wrong.sqlite"
    with closing(sqlite3.connect(wrong)) as db:
        db.execute("CREATE TABLE other (id TEXT)")
    with TestClient(create_app(Settings(model_database=wrong))) as client:
        assert client.get("/api/v1/models").status_code == 503
