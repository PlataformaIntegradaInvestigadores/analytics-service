"""Synthetic-only preparation, query, protocol, persistence and transport tests."""

import csv
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.data import documents as d
from app.data.centinela import FILES, ingest
from app.documents import main
from app.domain.common import AnalyticsError
from app.domain.text import prepare_text
from app.main import create_app


@pytest.fixture
def database(tmp_path):
    source = tmp_path / "exports"
    source.mkdir()
    records = [
        [
            "s1",
            "Shared science title",
            "Shared useful abstract",
            "Alpha | Beta",
            "2",
            "2024-01-01",
            "a",
            "x",
            "2024",
        ],
        [
            "s2",
            "Shared science title",
            "Shared useful abstract",
            "Alpha",
            "2",
            "2025-01-01",
            "a",
            "x",
            "2025",
        ],
        ["s3", "Title only science", "", "Beta", "2", "2025-02-02", "a", "y", "2025"],
        ["s4", "T", "x", "Gamma", "2", "2023-02-02", "a", "y", "2023"],
    ]
    rows = [
        records,
        [["s1", "x"], ["s1", "z"], ["s2", "x"], ["s3", "y"], ["s4", "y"]],
        [
            ["alpha", "s1"],
            ["beta", "s1"],
            ["alpha", "s2"],
            ["beta", "s3"],
            ["gamma", "s4"],
        ],
    ]
    for (name, columns), table in zip(FILES.items(), rows, strict=True):
        with (source / name).open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(columns)
            writer.writerows(table)
    path = tmp_path / "corpus.sqlite"
    ingest(source, path)
    return path


def test_unicode_preparation_keeps_original_inputs():
    result = prepare_text("  ＡI\nscience ", "Résumé\t世界")
    assert result["text"] == "AI science\nRésumé 世界"
    assert result["tokens"] == ["ai", "science", "résumé", "世界"]
    assert not prepare_text("Title", None)["has_abstract"]


def test_pages_details_and_descriptor_counts(database):
    before = database.read_bytes()
    assert d.article_page(database)["total"] == 4
    assert d.article_page(database, author="x", descriptor="ALPHA")["total"] == 2
    assert (
        d.article_page(database, year=2025, has_abstract=False)["items"][0][
            "article_id"
        ]
        == "s3"
    )
    assert d.article_page(database, has_abstract=True)["total"] == 3
    assert d.article_page(database, offset=100)["status"] == "empty"
    assert d.article_page(database, author="x' OR 1=1 --")["total"] == 0
    detail = d.article_detail(database, "s1")
    assert detail["authors"] == ["x", "z"]
    assert detail["descriptors"] == ["alpha", "beta"]
    assert d.descriptor_page(database, 1)["total"] == 3
    assert d.descriptor_page(database, offset=100)["status"] == "empty"
    assert d.summary(database)["training"] == "pending_use_clarification"
    assert database.read_bytes() == before
    with pytest.raises(AnalyticsError, match="Unknown article"):
        d.article_detail(database, "absent")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"limit": 0},
        {"offset": True},
        {"year": "2020"},
        {"has_abstract": 1},
        {"descriptor": " "},
        {"author": "x" * 257},
    ],
)
def test_query_guards(database, kwargs):
    with pytest.raises(AnalyticsError):
        d.article_page(database, **kwargs)


def test_selection_deduplication_and_immutable_workset(database, tmp_path):
    preview = d.preview(database, {})
    assert preview["counts"]["included"] == 1
    assert preview["counts"]["exclusion_reasons"] == {
        "duplicate_text": 1,
        "missing_abstract": 1,
        "insufficient_tokens": 1,
    }
    assert preview["duplicate_groups"] == [["s1", "s2"]]
    destination = tmp_path / "prepared.sqlite"
    assert d.save_workset(database, destination, {}) == preview
    assert d.working_manifest(destination) == preview
    kept = d.preview(
        database,
        {"duplicates": "keep", "missing_abstract": "title_only", "min_tokens": 1},
    )
    assert kept["counts"]["included"] == 4
    filtered = d.preview(database, {"start_year": 2025})
    assert filtered["included"][0]["article_id"] == "s2"
    assert filtered["counts"]["exclusion_reasons"]["outside_year_filter"] == 2
    with pytest.raises(ValidationError):
        d.preview(database, {"start_year": 2025, "end_year": 2020})
    for dest in (database, destination, tmp_path / "prepared.csv"):
        with pytest.raises(AnalyticsError, match="new external"):
            d.save_workset(database, dest, {})
    with sqlite3.connect(destination) as c:
        c.execute("UPDATE prepared SET payload='{}'")
    with pytest.raises(AnalyticsError, match="records differ"):
        d.working_manifest(destination)


def test_corrupted_manifest_and_missing_database(database, tmp_path):
    path = tmp_path / "prepared.sqlite"
    d.save_workset(database, path, {})
    with sqlite3.connect(path) as c:
        c.execute("UPDATE manifest SET payload='{}'")
    with pytest.raises(AnalyticsError, match="identity mismatch"):
        d.working_manifest(path)
    with pytest.raises(AnalyticsError, match="absent"):
        d.summary(tmp_path / "missing.sqlite")


def test_failed_preparation_publishes_nothing(database, tmp_path, monkeypatch):
    path = tmp_path / "prepared.sqlite"
    monkeypatch.setattr(
        d,
        "prepare_text",
        lambda *args: (_ for _ in ()).throw(AnalyticsError("injected", "failed")),
    )
    with pytest.raises(AnalyticsError, match="failed"):
        d.save_workset(database, path, {})
    assert not path.exists() and not list(tmp_path.glob(".workset-*"))


def test_candidate_protocol_and_structural_evaluation(database, tmp_path):
    path = tmp_path / "prepared.sqlite"
    manifest = d.save_workset(database, path, {})
    protocol = d.candidate_protocol(path, {"name": "development-candidate"})
    assert protocol["training"] == "pending_use_clarification"
    assert protocol["workset_id"] == manifest["workset_id"]
    payload = {
        "model_version": "caller-declared-v1",
        "fit_document_ids": ["s1"],
        "assignments": {"s1": "a"},
        "terms": {"a": ["one", "two"], "b": ["two", "three"]},
    }
    result = d.evaluate_outputs(path, payload)
    assert result["assignment_coverage"] == 1
    assert result["term_diversity"] == 0.75
    assert result["coherence"] is None and result["topic_sizes"]["b"] == 0
    payload["assignments"] = {}
    assert d.evaluate_outputs(path, payload)["unassigned_document_ids"] == ["s1"]
    for change in (
        {"fit_document_ids": ["s1", "s1"]},
        {"assignments": {"unknown": "a"}},
        {"assignments": {"s1": "unknown"}},
        {"terms": {"a": []}},
        {"terms": {"a": [" "]}},
        {"terms": {"a": ["same", "SAME"]}},
    ):
        with pytest.raises(AnalyticsError):
            d.evaluate_outputs(path, {**payload, **change})


def test_cli_all_operations(database, tmp_path, capsys):
    config = tmp_path / "config.json"
    config.write_text("{}")
    output = tmp_path / "prepared.sqlite"
    base = ["--database", str(database)]
    for op in ("articles", "descriptors", "summary"):
        assert main([op, *base]) == 0
        capsys.readouterr()
    assert main(["article", *base, "--id", "s1"]) == 0
    capsys.readouterr()
    assert main(["preview", *base, "--input", str(config)]) == 0
    capsys.readouterr()
    assert (
        main(["prepare", *base, "--input", str(config), "--output", str(output)]) == 0
    )
    capsys.readouterr()
    assert main(["workset", "--database", str(output)]) == 0
    capsys.readouterr()
    config.write_text(json.dumps({"name": "candidate"}))
    assert main(["protocol", "--database", str(output), "--input", str(config)]) == 0
    capsys.readouterr()
    config.write_text(
        json.dumps(
            {
                "model_version": "v1",
                "fit_document_ids": ["s1"],
                "assignments": {},
                "terms": {"a": ["one"]},
            }
        )
    )
    assert main(["evaluate", "--database", str(output), "--input", str(config)]) == 0
    capsys.readouterr()
    assert main(["preview", *base]) == 2
    capsys.readouterr()
    assert main(["summary", *base, "--year", "2020"]) == 2
    capsys.readouterr()
    assert main(["summary", "--database", str(tmp_path / "absent")]) == 2
    assert json.loads(capsys.readouterr().err)["error"] == "document_store_missing"


def test_http_contracts_and_local_guards(database, tmp_path):
    work = tmp_path / "prepared.sqlite"
    d.save_workset(database, work, {})
    client = TestClient(
        create_app(
            Settings(_env_file=None, corpus_database=database, workset_database=work)
        )
    )
    for url in (
        "/corpus/articles",
        "/corpus/articles/s1",
        "/corpus/descriptors",
        "/corpus/summary",
        "/corpus/workset",
    ):
        assert client.get("/api/v1" + url).status_code == 200
    assert client.get("/api/v1/corpus/articles/missing").status_code == 404
    assert client.get("/api/v1/corpus/articles?limit=101").status_code == 422
    assert client.post("/api/v1/corpus/worksets/preview", json={}).status_code == 200
    assert (
        client.post(
            "/api/v1/topics/candidates/protocol", json={"name": "candidate"}
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/topics/outputs/evaluate",
            json={
                "model_version": "v1",
                "fit_document_ids": ["s1"],
                "assignments": {},
                "terms": {"a": ["one"]},
            },
        ).status_code
        == 200
    )
    absent = TestClient(create_app(Settings(_env_file=None)))
    assert absent.get("/api/v1/corpus/articles").status_code == 503
    assert absent.get("/api/v1/corpus/workset").status_code == 503
    remote = TestClient(create_app(Settings(_env_file=None, environment="production")))
    assert remote.get("/api/v1/corpus/summary").status_code == 503
