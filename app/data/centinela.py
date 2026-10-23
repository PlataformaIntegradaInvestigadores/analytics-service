"""Transactional, streaming adapter for the three authorized development exports."""

import csv
import hashlib
import json
import os
import sqlite3
import tempfile
import unicodedata
from collections import Counter
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from app.domain.common import AnalyticsError, canonical_json, fingerprint
from app.domain.corpus import curate

FILES = {
    "articulos_ecuador_CLEAN.csv": [
        "scopus_id",
        "title",
        "abstract",
        "keywords",
        "cited_by_count",
        "publication_date",
        "affiliations",
        "authors",
        "year",
    ],
    "autor_articulo_CLEAN.csv": ["scopus_id", "authid"],
    "topic_article_CLEAN.csv": ["topic", "article_id"],
}


def normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def hashes(directory: Path) -> dict:
    result = {}
    for name in FILES:
        digest = hashlib.sha256()
        with (directory / name).open("rb") as stream:
            while chunk := stream.read(65536):
                digest.update(chunk)
        result[name] = digest.hexdigest()
    return result


def batches(path: Path, expected: list[str], size: int):
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream, strict=True)
            if reader.fieldnames != expected:
                raise AnalyticsError(
                    "corpus_schema_mismatch", f"Unexpected columns in {path.name}"
                )
            block = []
            for row in reader:
                if None in row or any(value is None for value in row.values()):
                    raise AnalyticsError(
                        "corpus_row_width", f"Invalid CSV row in {path.name}"
                    )
                block.append(row)
                if len(block) == size:
                    yield block
                    block = []
            if block:
                yield block
    except (UnicodeError, csv.Error) as exc:
        raise AnalyticsError(
            "corpus_encoding_or_csv", "Invalid UTF-8 or CSV structure"
        ) from exc


def _populate(connection, directory, size, before, processed):
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("BEGIN IMMEDIATE")
    connection.execute(
        "CREATE TABLE articles (article_id TEXT PRIMARY KEY, "
        "publication_date TEXT NOT NULL, year TEXT NOT NULL, "
        "document TEXT NOT NULL, original TEXT NOT NULL)"
    )
    connection.execute(
        "CREATE TABLE author_links (article_id TEXT REFERENCES articles(article_id), "
        "author_id TEXT NOT NULL, PRIMARY KEY(article_id,author_id))"
    )
    connection.execute(
        "CREATE TABLE descriptor_links (article_id TEXT "
        "REFERENCES articles(article_id), descriptor TEXT NOT NULL, "
        "canonical TEXT NOT NULL, keyword_match INTEGER NOT NULL, "
        "PRIMARY KEY(article_id,descriptor))"
    )
    connection.execute("CREATE TABLE manifest (payload TEXT NOT NULL)")
    years, months, january_first = Counter(), Counter(), Counter()
    missing_abstracts = missing_affiliations = day_one = article_count = 0
    name = "articulos_ecuador_CLEAN.csv"
    for block in batches(directory / name, FILES[name], size):
        records = [
            {
                "source": "centinela-development-export",
                "source_id": row["scopus_id"],
                "title": row["title"],
                "abstract": row["abstract"] or None,
                "keywords": [
                    word.strip() for word in row["keywords"].split("|") if word.strip()
                ],
                "publication_date": row["publication_date"],
                "retrieved_at": processed,
                "access": "metadata_only",
            }
            for row in block
        ]
        curated = curate(records, "empirical")
        if curated["quality"]["rejected_rows"] or curated["quality"]["duplicate_rows"]:
            raise AnalyticsError(
                "corpus_invalid_article",
                "Resolve rejected or repeated articles before ingestion",
            )
        docs = {doc["provenance"][0]["source_id"]: doc for doc in curated["documents"]}
        prepared = []
        for row in block:
            identifier, publication = row["scopus_id"], row["publication_date"]
            if (
                not identifier.strip()
                or identifier != identifier.strip()
                or row["year"] != publication[:4]
            ):
                raise AnalyticsError(
                    "corpus_invalid_article",
                    "Article ID/year disagrees with the source contract",
                )
            years[row["year"]] += 1
            months[publication[:7]] += 1
            day_one += publication.endswith("-01")
            if publication.endswith("-01-01"):
                january_first[row["year"]] += 1
            missing_abstracts += not row["abstract"].strip()
            missing_affiliations += not row["affiliations"].strip()
            prepared.append(
                (
                    identifier,
                    publication,
                    row["year"],
                    canonical_json(docs[identifier]),
                    canonical_json(row),
                )
            )
        connection.executemany("INSERT INTO articles VALUES (?,?,?,?,?)", prepared)
        article_count += len(block)
    if not article_count:
        raise AnalyticsError("empty_corpus", "At least one article is required")
    author_count = descriptor_count = matches = 0
    for name, columns in list(FILES.items())[1:]:
        for block in batches(directory / name, columns, size):
            prepared = []
            for row in block:
                if any(
                    not value.strip() or value != value.strip()
                    for value in row.values()
                ):
                    raise AnalyticsError(
                        "corpus_invalid_link",
                        "Relationship values must be nonblank without outer whitespace",
                    )
                if "authid" in row:
                    prepared.append((row["scopus_id"], row["authid"]))
                    author_count += 1
                else:
                    article = connection.execute(
                        "SELECT document FROM articles WHERE article_id=?",
                        (row["article_id"],),
                    ).fetchone()
                    if article is None:
                        raise AnalyticsError(
                            "corpus_orphan_link",
                            "Descriptor refers to an absent article",
                        )
                    keyword_match = normalized(row["topic"]) in {
                        normalized(word) for word in json.loads(article[0])["keywords"]
                    }
                    prepared.append(
                        (
                            row["article_id"],
                            row["topic"],
                            normalized(row["topic"]),
                            int(keyword_match),
                        )
                    )
                    descriptor_count += 1
                    matches += keyword_match
            if "authid" in columns:
                connection.executemany(
                    "INSERT INTO author_links VALUES (?,?)", prepared
                )
            else:
                connection.executemany(
                    "INSERT INTO descriptor_links VALUES (?,?,?,?)", prepared
                )
    if before != hashes(directory):
        raise AnalyticsError(
            "corpus_source_changed", "Source files changed during ingestion"
        )
    connection.execute(
        "CREATE INDEX descriptor_lookup ON descriptor_links(canonical,article_id)"
    )
    report = {
        "adapter_version": "centinela-development-corpus-v1",
        "source_sha256": before,
        "source_version": fingerprint(before),
        "processed_at": processed,
        "data_kind": "empirical",
        "use_scope": "development_only_pending_clarification",
        "articles": article_count,
        "author_links": author_count,
        "descriptor_links": descriptor_count,
        "keyword_matching_links": matches,
        "missing_abstracts": missing_abstracts,
        "missing_affiliations": missing_affiliations,
        "articles_by_year": dict(sorted(years.items())),
        "articles_by_month": dict(sorted(months.items())),
        "day_01_articles": day_one,
        "january_01_by_year": dict(sorted(january_first.items())),
        "articles_without_authors": connection.execute(
            "SELECT COUNT(*) FROM articles a WHERE NOT EXISTS "
            "(SELECT 1 FROM author_links l WHERE l.article_id=a.article_id)"
        ).fetchone()[0],
        "articles_without_descriptors": connection.execute(
            "SELECT COUNT(*) FROM articles a WHERE NOT EXISTS "
            "(SELECT 1 FROM descriptor_links l WHERE l.article_id=a.article_id)"
        ).fetchone()[0],
        "date_precision": "unverified",
        "historical_availability": "unknown",
        "coverage": "unverified_snapshot",
        "monthly_forecasting": "blocked_pending_date_precision_and_coverage",
        "descriptor_origin": "source_labels_not_fitted_topics",
        "policy": (
            "retrieved_at records local processing, never historical availability; "
            "citation counts are preserved only in original records, "
            "not predictive features"
        ),
    }
    connection.execute("INSERT INTO manifest VALUES (?)", (canonical_json(report),))
    connection.commit()
    return report


def ingest(directory: Path, database: Path, batch_size: int = 500) -> dict:
    directory, database = Path(directory).resolve(), Path(database).resolve()
    if (
        isinstance(batch_size, bool)
        or not isinstance(batch_size, int)
        or not 1 <= batch_size <= 1000
    ):
        raise AnalyticsError("invalid_batch_size", "Use 1..1000 articles per block")
    if database.is_relative_to(directory) or database.suffix != ".sqlite":
        raise AnalyticsError(
            "unsafe_corpus_destination",
            "Use an external .sqlite destination, outside the source directory",
        )
    if database.exists():
        raise AnalyticsError(
            "corpus_destination_exists",
            "Keep existing snapshots; choose a new destination",
        )
    before = hashes(directory)
    descriptor, temporary = tempfile.mkstemp(
        prefix=".corpus-", suffix=".sqlite", dir=database.parent
    )
    os.close(descriptor)
    temporary = Path(temporary)
    try:
        with closing(sqlite3.connect(temporary)) as connection:
            report = _populate(
                connection, directory, batch_size, before, datetime.now(UTC).isoformat()
            )
        # Same-directory hard link publishes atomically and refuses an existing target.
        os.link(temporary, database)
        return report
    except sqlite3.IntegrityError as exc:
        raise AnalyticsError(
            "corpus_relationship_or_identity_conflict",
            "Repeated article/link or an absent article reference",
        ) from exc
    finally:
        temporary.unlink(missing_ok=True)


def inspect(directory: Path, batch_size: int = 500) -> dict:
    with tempfile.TemporaryDirectory(prefix="centinela-audit-") as temporary:
        return ingest(directory, Path(temporary) / "audit.sqlite", batch_size)


def descriptor_counts(database: Path, descriptors: list[str]) -> dict:
    if not Path(database).is_file():
        raise AnalyticsError("corpus_snapshot_missing", "Snapshot does not exist")
    selected = sorted({normalized(term) for term in descriptors})
    if not 1 <= len(selected) <= 100 or any(
        not term or len(term) > 256 for term in selected
    ):
        raise AnalyticsError("invalid_descriptors", "Select 1..100 bounded descriptors")
    with closing(
        sqlite3.connect(Path(database).resolve().as_uri() + "?mode=ro", uri=True)
    ) as connection:
        report = json.loads(
            connection.execute("SELECT payload FROM manifest").fetchone()[0]
        )
        totals = connection.execute(
            "SELECT year,COUNT(*) FROM articles GROUP BY year ORDER BY year"
        ).fetchall()
        points = []
        for term in selected:
            counts = dict(
                connection.execute(
                    "SELECT a.year,COUNT(DISTINCT a.article_id) FROM articles a "
                    "JOIN descriptor_links l ON l.article_id=a.article_id "
                    "WHERE l.canonical=? GROUP BY a.year",
                    (term,),
                )
            )
            for year, total in totals:
                count = counts.get(year, 0)
                points.append(
                    {
                        "descriptor": term,
                        "year": year,
                        "snapshot_count": count,
                        "snapshot_denominator": total,
                        "snapshot_share": count / total,
                    }
                )
    return {
        "source_version": report["source_version"],
        "points": points,
        "coverage": "unverified_snapshot",
        "policy": (
            "Descriptive multi-label counts of distinct articles; shares across "
            "descriptors need not sum to one; no topic model or historical "
            "forecast is fitted"
        ),
    }
