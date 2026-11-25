"""Contract boundary fixtures, independent of empirical research results."""

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.application.topic_map import frozen_map
from app.core.config import Settings
from app.domain.common import AnalyticsError, fingerprint
from app.main import create_app


class Archive:
    def __init__(self, tmp_path):
        self.model = {"format": "nmf-json-v1", "components": [[1.0, 0.0], [1.0, 1.0]]}
        self.identifier = fingerprint(self.model)
        self.path = tmp_path / "models.sqlite"
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE fitted_models(id,payload)")
            db.execute(
                "INSERT INTO fitted_models VALUES (?,?)",
                (self.identifier, json.dumps(self.model)),
            )
        self.study = {
            "topic_model_id": self.identifier,
            "run_id": "fixture",
            "topics": [
                {"topic_id": "topic-0", "terms": ["a"]},
                {"topic_id": "topic-1", "terms": ["b"]},
            ],
        }
        self.study["report_sha256"] = fingerprint(self.study)
        self.tables = {
            "silver_prepared_documents": [
                {"document_id": str(i), "article_id": str(i), "year": 2000 + i}
                for i in range(3)
            ],
            "silver_topic_assignments": [
                {"document_id": str(i), "topic_id": t, "weights": json.dumps(w)}
                for i, t, w in [
                    (0, "topic-0", [1, 1]),
                    (1, "topic-1", [0, 2]),
                    (2, None, [0, 0]),
                ]
            ],
            "gold_annual_series": [
                {"year": 2000, "topic_id": "topic-0", "count": 1},
                {"year": 2001, "topic_id": "topic-1", "count": 1},
            ],
        }

    def read_blob(self, release, name):
        return json.dumps(self.study).encode()

    def object_path(self, release, name):
        return self.path

    def read_topic_model(self, release, identifier):
        return self.model

    def read_table(self, release, name):
        return self.tables[name]


def test_frozen_cosine_filters_denominators_and_ties(tmp_path):
    archive = Archive(tmp_path)
    release = {"release_id": "a" * 64}
    full, _ = frozen_map(archive, release)
    part, selected = frozen_map(archive, release, 2001, 2002)
    assert full["edges"] == part["edges"]
    assert full["edges"][0]["weight"] == pytest.approx(2**-0.5)
    assert full["denominator"] == 3 and full["unassigned"] == 1
    assert full["nodes"][0]["share"] == pytest.approx(1 / 3)
    assert part["nodes"][0]["count"] == 0 and len(selected) == 2
    assert part["denominator"] == 2 and part["unassigned"] == 1
    empty, _ = frozen_map(archive, release, 2010, 2020, 1.0)
    assert empty["denominator"] == 0 and empty["edges"] == []
    with pytest.raises(AnalyticsError):
        frozen_map(archive, release, 2002, 2000)
    with pytest.raises(AnalyticsError):
        frozen_map(archive, release, threshold=float("nan"))


@pytest.mark.parametrize("mutation", ["duplicate", "mismatch", "series", "fingerprint"])
def test_corrupt_inputs_rejected(tmp_path, mutation):
    archive = Archive(tmp_path)
    if mutation == "duplicate":
        archive.tables["silver_prepared_documents"].append(
            archive.tables["silver_prepared_documents"][0]
        )
    elif mutation == "mismatch":
        archive.tables["silver_topic_assignments"][0]["topic_id"] = "topic-1"
    elif mutation == "series":
        archive.tables["gold_annual_series"][0]["count"] = 9
    else:
        archive.study["run_id"] = "tampered"
    with pytest.raises(AnalyticsError):
        frozen_map(archive, {"release_id": "a" * 64})


def test_api_configuration_filters_and_access():
    client = TestClient(create_app(Settings()))
    assert client.get("/api/v1/topic-map").status_code == 503
    assert client.get("/api/v1/topic-map?threshold=1.5").status_code == 422
    assert (
        client.get(
            "/api/v1/topic-map/documents?topic_id=topic-0&release_id=bad&limit=100"
        ).status_code
        == 422
    )
    protected = TestClient(
        create_app(
            Settings(
                environment="staging",
                identity_validation_url="http://identity-service/internal/auth/validate-token/",
                identity_allowed_users=["jairo"],
            )
        )
    )
    assert protected.get("/api/v1/topic-map").status_code == 401
    assert (
        protected.get(
            "/api/v1/topic-map/documents?topic_id=topic-0&release_id=bad"
        ).status_code
        == 401
    )
