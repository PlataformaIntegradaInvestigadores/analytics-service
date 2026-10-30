"""Synthetic exports test the real-format adapter without copying restricted data."""

import csv
import json
import sqlite3

import pytest

from app.corpus import main
from app.data.centinela import (
    FILES,
    batches,
    descriptor_counts,
    hashes,
    ingest,
    inspect,
)
from app.domain.common import AnalyticsError


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    tables = {
        "articulos_ecuador_CLEAN.csv": [
            [
                "s1",
                "Synthetic title",
                "",
                "Alpha | Beta",
                "100",
                "2024-01-01",
                "",
                "a1",
                "2024",
            ],
            [
                "s2",
                "Synthetic second",
                "Synthetic abstract",
                "Alpha",
                "0",
                "2025-03-02",
                "x",
                "a2",
                "2025",
            ],
        ],
        "autor_articulo_CLEAN.csv": [["s1", "a1"], ["s1", "a2"], ["s2", "a2"]],
        "topic_article_CLEAN.csv": [["ALPHA", "s1"], ["Beta", "s1"], ["alpha", "s2"]],
    }
    for name, rows in tables.items():
        with (root / name).open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(FILES[name])
            writer.writerows(rows)
    return root


def modify(source, name, change):
    path = source / name
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.reader(stream))
    change(rows)
    with path.open("w", encoding="utf-8", newline="") as stream:
        csv.writer(stream).writerows(rows)


def test_ingestion_streams_and_preserves_source_and_unknown_dates(source, tmp_path):
    original = hashes(source)
    database = tmp_path / "snapshot.sqlite"
    report = ingest(source, database, batch_size=1)
    assert hashes(source) == original
    assert report["articles"] == 2
    assert report["author_links"] == 3
    assert report["keyword_matching_links"] == 3
    assert report["missing_abstracts"] == 1
    assert report["january_01_by_year"] == {"2024": 1}
    assert report["articles_without_authors"] == 0
    assert report["articles_without_descriptors"] == 0
    assert report["date_precision"] == "unverified"
    assert report["monthly_forecasting"].startswith("blocked")
    with sqlite3.connect(database) as connection:
        doc = json.loads(
            connection.execute(
                "SELECT document FROM articles WHERE article_id='s1'"
            ).fetchone()[0]
        )
        raw = json.loads(
            connection.execute(
                "SELECT original FROM articles WHERE article_id='s1'"
            ).fetchone()[0]
        )
    assert doc["doi"] is None and doc["available_on"] is None
    assert doc["language"] is None and doc["full_text"] is None
    assert doc["keywords"] == ["Alpha", "Beta"]
    assert "cited_by_count" not in doc and raw["cited_by_count"] == "100"
    repeated = inspect(source, 2)
    assert repeated["source_version"] == report["source_version"]
    assert not list(tmp_path.glob(".corpus-*"))


def test_multilabel_counts_do_not_multiply_denominators(source, tmp_path):
    modify(source, "topic_article_CLEAN.csv", lambda rows: rows.append(["alpha", "s1"]))
    database = tmp_path / "snapshot.sqlite"
    ingest(source, database)
    before = database.read_bytes()
    result = descriptor_counts(database, ["ALPHA", "beta", "missing"])
    points = {(p["descriptor"], p["year"]): p for p in result["points"]}
    assert points["alpha", "2024"]["snapshot_count"] == 1
    assert points["beta", "2024"]["snapshot_share"] == 1
    assert points["alpha", "2024"]["snapshot_denominator"] == 1
    assert points["missing", "2024"]["snapshot_count"] == 0
    assert result["coverage"] == "unverified_snapshot"
    assert database.read_bytes() == before


@pytest.mark.parametrize("size", [0, 1001, True, "10"])
def test_invalid_block_sizes(source, tmp_path, size):
    with pytest.raises(AnalyticsError, match="1..1000"):
        ingest(source, tmp_path / "x.sqlite", size)


def test_preserve_existing_destination_and_source_directory(source, tmp_path):
    for dest in (source / "x.sqlite", tmp_path / "x.csv"):
        with pytest.raises(AnalyticsError, match="external .sqlite"):
            ingest(source, dest)
    dest = tmp_path / "existing.sqlite"
    dest.write_bytes(b"keep")
    with pytest.raises(AnalyticsError, match="existing snapshots"):
        ingest(source, dest)
    assert dest.read_bytes() == b"keep"


@pytest.mark.parametrize(
    "name,change,code",
    [
        (
            "articulos_ecuador_CLEAN.csv",
            lambda r: r[0].append("unknown"),
            "corpus_schema_mismatch",
        ),
        ("articulos_ecuador_CLEAN.csv", lambda r: r[1].pop(), "corpus_row_width"),
        (
            "articulos_ecuador_CLEAN.csv",
            lambda r: r[1].__setitem__(1, ""),
            "corpus_invalid_article",
        ),
        (
            "articulos_ecuador_CLEAN.csv",
            lambda r: r[1].__setitem__(8, "2023"),
            "corpus_invalid_article",
        ),
        (
            "articulos_ecuador_CLEAN.csv",
            lambda r: r[1].__setitem__(0, " s1"),
            "corpus_invalid_article",
        ),
        (
            "articulos_ecuador_CLEAN.csv",
            lambda r: r.append(r[1]),
            "corpus_relationship_or_identity_conflict",
        ),
        (
            "autor_articulo_CLEAN.csv",
            lambda r: r[1].__setitem__(0, "absent"),
            "corpus_relationship_or_identity_conflict",
        ),
        (
            "autor_articulo_CLEAN.csv",
            lambda r: r.append(r[1]),
            "corpus_relationship_or_identity_conflict",
        ),
        (
            "topic_article_CLEAN.csv",
            lambda r: r[1].__setitem__(1, "absent"),
            "corpus_orphan_link",
        ),
        (
            "topic_article_CLEAN.csv",
            lambda r: r[1].__setitem__(0, " "),
            "corpus_invalid_link",
        ),
        (
            "articulos_ecuador_CLEAN.csv",
            lambda r: r.__delitem__(slice(1, None)),
            "empty_corpus",
        ),
    ],
)
def test_invalid_sources_roll_back(source, tmp_path, name, change, code):
    modify(source, name, change)
    destination = tmp_path / "snapshot.sqlite"
    with pytest.raises(AnalyticsError) as exc:
        ingest(source, destination, 1)
    assert exc.value.code == code
    assert not destination.exists()
    assert not list(tmp_path.glob(".corpus-*"))


def test_duplicates_inside_block_are_rejected(source, tmp_path):
    modify(source, "articulos_ecuador_CLEAN.csv", lambda r: r.append(r[1]))
    with pytest.raises(AnalyticsError, match="repeated articles"):
        ingest(source, tmp_path / "x.sqlite", 100)


def test_encoding_failure(source, tmp_path):
    (source / "articulos_ecuador_CLEAN.csv").write_bytes(b"\xff")
    with pytest.raises(AnalyticsError, match="UTF-8"):
        ingest(source, tmp_path / "x.sqlite")


def test_csv_error_and_source_change(source, tmp_path, monkeypatch):
    (source / "articulos_ecuador_CLEAN.csv").write_text(
        ",".join(FILES["articulos_ecuador_CLEAN.csv"]) + '\n"unclosed', encoding="utf-8"
    )
    with pytest.raises(AnalyticsError, match="CSV"):
        list(
            batches(
                source / "articulos_ecuador_CLEAN.csv",
                FILES["articulos_ecuador_CLEAN.csv"],
                1,
            )
        )


def test_changed_source_is_not_published(source, tmp_path, monkeypatch):
    original = hashes(source)
    calls = iter([original, {}])
    monkeypatch.setattr("app.data.centinela.hashes", lambda directory: next(calls))
    with pytest.raises(AnalyticsError, match="changed during"):
        ingest(source, tmp_path / "x.sqlite")
    assert not (tmp_path / "x.sqlite").exists()


def test_missing_links_and_unmatched_descriptor_are_reported(source, tmp_path):
    modify(source, "autor_articulo_CLEAN.csv", lambda r: r.__delitem__(slice(1, None)))
    modify(
        source,
        "topic_article_CLEAN.csv",
        lambda r: r.__setitem__(slice(1, None), [["not-a-keyword", "s1"]]),
    )
    result = ingest(source, tmp_path / "x.sqlite")
    assert result["articles_without_authors"] == 2
    assert result["articles_without_descriptors"] == 1
    assert result["keyword_matching_links"] == 0


def test_cli_operations(source, tmp_path, capsys):
    directory = ["--directory", str(source)]
    database = ["--database", str(tmp_path / "x.sqlite")]
    assert main(["inspect", *directory]) == 0
    assert json.loads(capsys.readouterr().out)["articles"] == 2
    assert main(["ingest", *directory, *database]) == 0
    capsys.readouterr()
    assert main(["descriptors", *database, "--descriptor", "alpha"]) == 0
    assert json.loads(capsys.readouterr().out)["points"]
    assert main(["ingest", *directory, *database]) == 2
    assert json.loads(capsys.readouterr().err)["error"] == "corpus_destination_exists"
    assert main(["inspect", "--directory", str(tmp_path / "missing")]) == 2
    assert json.loads(capsys.readouterr().err)["error"] == "corpus_io_error"


def test_descriptor_query_limits_and_absent_database(source, tmp_path):
    database = tmp_path / "x.sqlite"
    with pytest.raises(AnalyticsError, match="does not exist"):
        descriptor_counts(database, ["a"])
    ingest(source, database)
    for values in ([], [" "], ["x" * 257], [str(i) for i in range(101)]):
        with pytest.raises(AnalyticsError, match="1..100"):
            descriptor_counts(database, values)
