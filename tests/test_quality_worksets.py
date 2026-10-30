"""Aggregate reconciliation and immutable preparation on synthetic exports."""

import csv
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.data import documents, quality
from app.data.centinela import FILES, ingest
from app.documents import main
from app.domain.common import AnalyticsError
from app.main import create_app


@pytest.fixture
def database(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    abstract = " ".join(["science"] * 60)
    articles = [
        [
            "s1",
            "Shared research title",
            abstract,
            "Alpha",
            "0",
            "2024-01-01",
            "a",
            "x",
            "2024",
        ],
        [
            "s2",
            "Shared research title",
            abstract,
            "Alpha",
            "0",
            "2025-01-01",
            "a",
            "x",
            "2025",
        ],
        ["s3", "Title only science", "", "Beta", "0", "2025-02-02", "a", "y", "2025"],
        ["s4", "T", "x", "Beta", "0", "2023-02-02", "a", "y", "2023"],
    ]
    tables = [
        articles,
        [[row[0], "author"] for row in articles],
        [[row[3].lower(), row[0]] for row in articles],
    ]
    for (name, columns), rows in zip(FILES.items(), tables, strict=True):
        with (source / name).open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(columns)
            writer.writerows(rows)
    path = tmp_path / "corpus.sqlite"
    ingest(source, path)
    return path


def test_quality_reconciles_dates_lengths_duplicates_and_unknowns(database, capsys):
    before = database.read_bytes()
    result = quality.quality_report(database)
    assert result["articles"] == 4
    assert result["missing_abstracts"] == 1
    assert sum(result["abstract_token_buckets"].values()) == 4
    assert result["abstract_token_buckets"]["50_199"] == 2
    assert result["duplicate_text_groups"] == result["duplicate_text_excess"] == 1
    assert result["dates"]["day_one"] == result["dates"]["january_one"] == 2
    assert result["language"] == {
        "unknown": 4,
        "declared": 0,
        "detection": "not_executed",
    }
    assert result == quality.quality_report(database)
    assert main(["quality", "--database", str(database)]) == 0
    assert json.loads(capsys.readouterr().out) == result
    assert database.read_bytes() == before


def test_quality_long_and_empty_corpora(database):
    with sqlite3.connect(database) as connection:
        document = json.loads(
            connection.execute(
                "SELECT document FROM articles WHERE article_id='s4'"
            ).fetchone()[0]
        )
        document.update(abstract=" ".join(["word"] * 201), language="en")
        connection.execute(
            "UPDATE articles SET document=? WHERE article_id='s4'",
            (json.dumps(document),),
        )
    assert quality.quality_report(database)["abstract_token_buckets"]["200_plus"] == 1
    assert quality.quality_report(database)["language"]["declared"] == 1
    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM articles")
    report = quality.quality_report(database)
    assert report["articles"] == 0
    assert report["duplicate_text_excess"] == 0


def test_preview_and_creation_reconcile_without_disclosing_records(database, tmp_path):
    before = database.read_bytes()
    preview = quality.preview(database, {})
    assert preview["counts"]["included"] == 1
    assert preview["counts"]["included"] + preview["counts"]["excluded"] == 4
    assert "included" not in preview and "excluded" not in preview
    directory = tmp_path / "prepared"
    created = quality.create_workset(database, directory, {})
    assert created["workset_id"] == preview["workset_id"]
    assert created["reused"] is False
    saved = directory / (created["workset_id"] + ".sqlite")
    original = saved.read_bytes()
    assert quality.create_workset(database, directory, {})["reused"] is True
    assert quality.stored_workset(directory, created["workset_id"]) == preview
    assert saved.read_bytes() == original and database.read_bytes() == before
    alternative = quality.create_workset(database, directory, {"duplicates": "keep"})
    assert alternative["workset_id"] != created["workset_id"]
    assert len(list(directory.iterdir())) == 2
    with pytest.raises(AnalyticsError, match="Preview no longer"):
        quality.create_workset(database, directory, {}, "0" * 64)
    assert len(list(directory.iterdir())) == 2


def test_storage_paths_identity_and_corruption_are_checked(database, tmp_path):
    with pytest.raises(AnalyticsError, match="Configure"):
        quality.storage_directory(None)
    with pytest.raises(AnalyticsError, match="outside"):
        quality.storage_directory(quality.__file__)
    for identifier in ("../escape", "G" * 64):
        with pytest.raises(AnalyticsError, match="SHA-256"):
            quality.stored_workset(tmp_path, identifier)
    with pytest.raises(AnalyticsError, match="does not exist"):
        quality.stored_workset(tmp_path, "0" * 64)
    saved = quality.create_workset(database, tmp_path / "prepared", {})
    path = tmp_path / "prepared" / (saved["workset_id"] + ".sqlite")
    path.rename(path.with_name("0" * 64 + ".sqlite"))
    with pytest.raises(AnalyticsError, match="filename"):
        quality.stored_workset(path.parent, "0" * 64)
    renamed = path.with_name("0" * 64 + ".sqlite")
    with sqlite3.connect(renamed) as connection:
        connection.execute("UPDATE prepared SET payload='{}'")
    with pytest.raises(AnalyticsError, match="Prepared records"):
        quality.stored_workset(path.parent, "0" * 64)


def test_failed_creation_cleans_temporary_files(database, tmp_path, monkeypatch):
    def fail(*args):
        raise AnalyticsError("test_failure", "Deliberate storage failure")

    monkeypatch.setattr(documents, "save_workset", fail)
    directory = tmp_path / "prepared"
    with pytest.raises(AnalyticsError):
        quality.create_workset(database, directory, {})
    assert not list(directory.iterdir())


def test_http_preparation_quality_and_restrictions(database, tmp_path):
    settings = Settings(
        environment="local",
        corpus_database=database,
        workset_directory=tmp_path / "prepared",
    )
    with TestClient(create_app(settings)) as client:
        report = client.get("/api/v1/corpus/quality")
        assert report.status_code == 200 and report.json()["articles"] == 4
        preview = client.post("/api/v1/corpus/preparation/preview", json={})
        assert preview.status_code == 200 and "included" not in preview.json()
        payload = {
            "configuration": {},
            "expected_workset_id": preview.json()["workset_id"],
        }
        created = client.post("/api/v1/corpus/worksets", json=payload)
        assert created.status_code == 200 and created.json()["reused"] is False
        identifier = created.json()["workset_id"]
        assert (
            client.get("/api/v1/corpus/worksets/" + identifier).json() == preview.json()
        )
        assert client.get("/api/v1/corpus/worksets/" + "0" * 64).status_code == 404
        assert client.get("/api/v1/corpus/worksets/invalid").status_code == 422
        assert (
            client.post(
                "/api/v1/corpus/preparation/preview",
                json={"start_year": 2025, "end_year": 2024},
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/v1/corpus/worksets", json={"destination": "arbitrary.sqlite"}
            ).status_code
            == 422
        )
    with TestClient(
        create_app(Settings(environment="local", corpus_database=database))
    ) as client:
        assert client.post("/api/v1/corpus/worksets", json=payload).status_code == 503
        assert client.get("/api/v1/corpus/worksets/" + "0" * 64).status_code == 503
    with TestClient(
        create_app(Settings(environment="production", corpus_database=database))
    ) as client:
        assert client.get("/api/v1/corpus/quality").status_code == 503
        assert (
            client.post("/api/v1/corpus/worksets", json={}).json()["detail"]["code"]
            == "integration_pending"
        )
