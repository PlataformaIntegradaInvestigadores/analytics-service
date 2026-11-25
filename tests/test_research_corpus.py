"""Contract/rollback fixtures, separate from the real-corpus execution evidence."""

import csv
import io
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.data import documents, quality, research_corpus
from app.domain.common import AnalyticsError
from app.main import create_app
from app.research import main


def write_rows(directory, name, rows, *, wrapped=False, index=False):
    header = list(research_corpus.SCHEMAS[name])
    if index:
        header.insert(0, "")
    with (directory / (name + ".csv")).open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for row in rows:
            if wrapped:
                buffer = io.StringIO(newline="")
                csv.writer(buffer).writerow(row)
                writer.writerow([buffer.getvalue().rstrip("\r\n")])
            else:
                writer.writerow(row)


@pytest.fixture
def delivery(tmp_path):
    directory = tmp_path / "source"
    directory.mkdir()
    rows = {
        "articles": [
            [
                "001",
                "Text mining",
                "2020-01-01",
                "https://doi.org/10.9999/SAME",
                "Scientific text and topics",
                "9",
                "8",
                "False",
            ],
            [
                "002",
                "Forecast research",
                "2021-01-01",
                "10.9999/same",
                "Annual research patterns",
                "1",
                "1",
                "True",
            ],
            ["003", "Title only", "2022-01-01", "invalid", "None", "0", "0", "False"],
        ],
        "authors": [["007", "A", "B", "B A", "A"]],
        "affiliations": [["008", "Institution", "", "Country"]],
        "author_keywords": [["009", "text mining"]],
        "articles_authors": [
            ["0", "001", "007"],
            ["1", "001", "007"],
            ["2", "absent", "007"],
        ],
        "articles_affiliations": [["0", "001", "008"]],
        "articles_author_keywords": [["0", "001", "009", "different label"]],
        "authors_affiliations": [["0", "007", "008"]],
    }
    for name, values in rows.items():
        write_rows(
            directory,
            name,
            values,
            wrapped=name == "articles",
            index=name in research_corpus.RELATIONSHIPS,
        )
    return directory


def ingest(delivery, target):
    return research_corpus.ingest_research(
        delivery, target, approval_reference="test contract reference"
    )


def test_preserve_source_identity_and_raw_relationships(delivery, tmp_path):
    before = research_corpus._hashes(delivery)
    target = tmp_path / "research.sqlite"
    report = ingest(delivery, target)
    assert report["articles"] == 3
    assert report["files"]["articles"]["decoded_wrapped_records"] == 3
    assert report["missing_abstracts"] == 1
    assert report["invalid_doi_syntax"] == 1
    assert not report["source_flags_applied_as_filter"]
    assert report["relationships"]["articles_authors"] == {
        "original": 3,
        "orphan_rows": 1,
        "duplicate_valid_pairs": 1,
        "valid_distinct": 1,
    }
    first = documents.article_detail(target, "001")["document"]
    second = documents.article_detail(target, "002")["document"]
    assert first["doi"] == second["doi"] == "10.9999/same"
    assert first["document_id"] != second["document_id"]
    assert first["source_corpus_flag"] == "False" and first["abstract"]
    assert first["available_on"] is None and first["full_text"] is None
    assert documents.article_detail(target, "003")["document"]["doi"] is None
    assert documents.article_page(target, author="007")["total"] == 1
    assert documents.article_page(target, descriptor="TEXT MINING")["total"] == 1
    with sqlite3.connect(target) as db:
        assert (
            db.execute("SELECT COUNT(*) FROM raw_articles_authors").fetchone()[0] == 3
        )
        assert (
            db.execute(
                "SELECT author_keyword FROM raw_articles_author_keywords"
            ).fetchone()[0]
            == "different label"
        )
        assert (
            json.loads(
                db.execute(
                    "SELECT original FROM articles WHERE article_id='001'"
                ).fetchone()[0]
            )["author_count"]
            == "9"
        )
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert before == research_corpus._hashes(delivery)
    assert not list(tmp_path.glob(".research-*"))


def test_queries_preparation_quality_and_api(delivery, tmp_path):
    target = tmp_path / "research.sqlite"
    ingest(delivery, target)
    assert documents.summary(target)["status"] == "ready_for_research_preparation"
    config = {"start_year": 2020, "end_year": 2022, "min_tokens": 1}
    preview = documents.preview(target, config)
    assert preview["counts"]["included"] == 2
    assert preview["purpose"] == "research_preparation_not_final_temporal_partition"
    assert preview["training"] == "pending_model_protocol"
    assert quality.quality_report(target)["policy"].startswith("Research snapshot;")
    app = create_app(Settings(corpus_database=target))
    with TestClient(app) as client:
        page = client.get("/api/v1/corpus/articles", params={"has_abstract": False})
        assert page.status_code == 200 and page.json()["total"] == 1
        assert (
            client.get("/api/v1/corpus/articles/001").json()["document"]["provenance"][
                0
            ]["source"]
            == research_corpus.SOURCE
        )
        assert client.get("/api/v1/corpus/quality").status_code == 200


@pytest.mark.parametrize(
    "mutation,code",
    [
        ("duplicate", "research_identity_conflict"),
        ("width", "research_row_width"),
        ("schema", "research_schema_mismatch"),
        ("blank_id", "research_invalid_id"),
        ("date", "invalid_date"),
        ("title", "research_invalid_article"),
        ("empty", "empty_corpus"),
    ],
)
def test_failure_never_publishes_partial_snapshot(delivery, tmp_path, mutation, code):
    row = ["001", "Title", "2020-01-01", "", "Text", "1", "1", "False"]
    if mutation == "schema":
        (delivery / "articles.csv").write_text("wrong\n", encoding="utf-8")
    else:
        if mutation == "width":
            row.pop()
        if mutation == "blank_id":
            row[0] = " 001"
        if mutation == "date":
            row[2] = "2020-99-99"
        if mutation == "title":
            row[1] = "None"
        rows = [row, row] if mutation == "duplicate" else [row]
        write_rows(delivery, "articles", [] if mutation == "empty" else rows)
    target = tmp_path / "research.sqlite"
    with pytest.raises(AnalyticsError) as error:
        ingest(delivery, target)
    assert error.value.code == code
    assert not target.exists() and not list(tmp_path.glob(".research-*"))


def test_destinations_authorization_and_cli(delivery, tmp_path, capsys):
    with pytest.raises(AnalyticsError, match="external"):
        ingest(delivery, delivery / "inside.sqlite")
    target = tmp_path / "cli.sqlite"
    assert (
        main(
            [
                "ingest",
                "--directory",
                str(delivery),
                "--database",
                str(target),
                "--approval-reference",
                "test contract reference",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["articles"] == 3
    before = target.read_bytes()
    with pytest.raises(AnalyticsError) as error:
        ingest(delivery, target)
    assert error.value.code == "corpus_destination_exists"
    assert before == target.read_bytes()
    with pytest.raises(AnalyticsError) as error:
        research_corpus.ingest_research(
            delivery, tmp_path / "none.sqlite", approval_reference=""
        )
    assert error.value.code == "approval_reference_required"
    assert (
        main(
            [
                "ingest",
                "--directory",
                str(delivery),
                "--database",
                str(target),
                "--approval-reference",
                "test",
            ]
        )
        == 2
    )
    assert json.loads(capsys.readouterr().err)["error"] == "corpus_destination_exists"


def test_detect_source_change_and_rollback(delivery, tmp_path, monkeypatch):
    original = research_corpus._hashes
    calls = 0

    def changed(directory):
        nonlocal calls
        result = original(directory)
        calls += 1
        if calls > 1:
            result["articles.csv"] = "changed"
        return result

    monkeypatch.setattr(research_corpus, "_hashes", changed)
    target = tmp_path / "changed.sqlite"
    with pytest.raises(AnalyticsError) as error:
        ingest(delivery, target)
    assert error.value.code == "corpus_source_changed"
    assert not target.exists() and not list(tmp_path.glob(".research-*"))
