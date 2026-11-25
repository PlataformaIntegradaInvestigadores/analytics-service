"""Immutable adapter for the eight-table Centinela research delivery.

Raw rows are retained; valid distinct links feed existing document queries.
This local adapter does not replace the platform's Neo4j/MongoDB or Lakehouse.
"""

import csv
import io
import os
import re
import sqlite3
import tempfile
from collections import Counter
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote

from app.core.provenance import sha256_file
from app.data.centinela import normalized
from app.domain.common import AnalyticsError, canonical_json, fingerprint, parse_day
from app.domain.corpus import curate

SOURCE = "centinela-research-delivery"
SCHEMAS = {
    "articles": (
        "identifier",
        "title",
        "publication_date",
        "doi",
        "abstract",
        "author_count",
        "affiliation_count",
        "corpus",
    ),
    "authors": ("identifier", "first_name", "last_name", "auth_name", "initials"),
    "affiliations": ("identifier", "affiliation_name", "city", "country"),
    "author_keywords": ("identifier", "name"),
    "articles_authors": ("article_id", "author_id"),
    "articles_affiliations": ("article_id", "affiliation_id"),
    "articles_author_keywords": (
        "article_id",
        "author_keyword_id",
        "author_keyword",
    ),
    "authors_affiliations": ("author_id", "affiliation_id"),
}
RELATIONSHIPS = {
    "articles_authors": (("article_id", "articles"), ("author_id", "authors")),
    "articles_affiliations": (
        ("article_id", "articles"),
        ("affiliation_id", "affiliations"),
    ),
    "articles_author_keywords": (
        ("article_id", "articles"),
        ("author_keyword_id", "author_keywords"),
    ),
    "authors_affiliations": (
        ("author_id", "authors"),
        ("affiliation_id", "affiliations"),
    ),
}


def _absent(value):
    return value.strip().casefold() in ("", "none", "null", "nan", "n/a")


def _hashes(directory):
    return {name + ".csv": sha256_file(directory / (name + ".csv")) for name in SCHEMAS}


def _read_raw(connection, directory):
    reports = {}
    for name, expected in SCHEMAS.items():
        with (directory / (name + ".csv")).open(
            encoding="utf-8-sig", newline=""
        ) as stream:
            reader = csv.reader(stream, strict=True)
            header = next(reader, [])
            indexed = name in RELATIONSHIPS and header == ["", *expected]
            if header != list(expected) and not indexed:
                raise AnalyticsError("research_schema_mismatch", name)
            columns = ["_export_index", *expected] if indexed else list(expected)
            sql_columns = ",".join('"' + c + '" TEXT' for c in columns)
            connection.execute(
                f'CREATE TABLE "raw_{name}" (_input_row INTEGER, {sql_columns})'
            )
            insert = (
                f'INSERT INTO "raw_{name}" VALUES ('
                + ",".join("?" for _ in range(len(columns) + 1))
                + ")"
            )
            count = wrapped = 0
            batch = []
            for number, row in enumerate(reader, 2):
                decoded = False
                for _ in range(2):
                    if len(row) != 1:
                        break
                    nested = list(csv.reader(io.StringIO(row[0]), strict=True))
                    if len(nested) != 1 or nested[0] == row:
                        break
                    row, decoded = nested[0], True
                if len(row) != len(columns):
                    raise AnalyticsError(
                        "research_row_width", f"{name}.csv record {number}"
                    )
                for key in (
                    "identifier",
                    "article_id",
                    "author_id",
                    "affiliation_id",
                    "author_keyword_id",
                ):
                    if key in columns:
                        value = row[columns.index(key)]
                        if _absent(value) or value != value.strip():
                            raise AnalyticsError("research_invalid_id", name)
                batch.append((number, *row))
                count += 1
                wrapped += decoded
                if len(batch) == 500:
                    connection.executemany(insert, batch)
                    batch.clear()
            connection.executemany(insert, batch)
            if "identifier" in expected:
                connection.execute(
                    f'CREATE UNIQUE INDEX "raw_{name}_id" '
                    f'ON "raw_{name}" (identifier)'
                )
            reports[name] = {"records": count, "decoded_wrapped_records": wrapped}
    return reports


def _links(connection):
    reports = {}
    for name, pairs in RELATIONSHIPS.items():
        left, right = pairs
        for column, _ in pairs:
            connection.execute(
                f'CREATE INDEX "raw_{name}_{column}" ON "raw_{name}" ("{column}")'
            )
        joined = (
            f'FROM "raw_{name}" l '
            f'JOIN "raw_{left[1]}" a ON l."{left[0]}"=a.identifier '
            f'JOIN "raw_{right[1]}" b ON l."{right[0]}"=b.identifier'
        )
        total = connection.execute(f'SELECT COUNT(*) FROM "raw_{name}"').fetchone()[0]
        valid = connection.execute("SELECT COUNT(*) " + joined).fetchone()[0]
        connection.execute(
            f'CREATE TABLE "valid_{name}" AS SELECT DISTINCT '
            f'l."{left[0]}",l."{right[0]}" ' + joined
        )
        distinct = connection.execute(
            f'SELECT COUNT(*) FROM "valid_{name}"'
        ).fetchone()[0]
        reports[name] = {
            "original": total,
            "orphan_rows": total - valid,
            "duplicate_valid_pairs": valid - distinct,
            "valid_distinct": distinct,
        }
    connection.execute(
        "CREATE TABLE author_links AS SELECT article_id,author_id "
        "FROM valid_articles_authors"
    )
    connection.execute(
        "CREATE UNIQUE INDEX author_lookup ON author_links(article_id,author_id)"
    )
    connection.execute(
        "CREATE TABLE descriptor_links (article_id TEXT,descriptor TEXT,"
        "canonical TEXT,keyword_match INTEGER,PRIMARY KEY(article_id,descriptor))"
    )
    for article, term in connection.execute(
        "SELECT DISTINCT l.article_id,k.name FROM valid_articles_author_keywords l "
        "JOIN raw_author_keywords k ON l.author_keyword_id=k.identifier "
        "ORDER BY l.article_id,k.name"
    ):
        if not _absent(term):
            connection.execute(
                "INSERT INTO descriptor_links VALUES (?,?,?,1)",
                (article, term, normalized(term)),
            )
    connection.execute(
        "CREATE INDEX descriptor_lookup ON descriptor_links(canonical,article_id)"
    )
    connection.execute(
        "CREATE INDEX descriptor_article ON descriptor_links(article_id)"
    )
    return reports


def _documents(connection, processed):
    connection.execute(
        "CREATE TABLE articles (article_id TEXT PRIMARY KEY,publication_date TEXT,"
        "year TEXT,document TEXT,original TEXT)"
    )
    years, flags = Counter(), Counter()
    count = absent = invalid_doi = missing_doi = day_one = january_one = 0
    for values in connection.execute(
        "SELECT "
        + ",".join(SCHEMAS["articles"])
        + " FROM raw_articles ORDER BY identifier"
    ):
        original = dict(zip(SCHEMAS["articles"], values, strict=True))
        identifier, publication = original["identifier"], original["publication_date"]
        parse_day(publication)
        if _absent(original["title"]):
            raise AnalyticsError("research_invalid_article", identifier)
        abstract = None if _absent(original["abstract"]) else original["abstract"]
        keywords = [
            r[0]
            for r in connection.execute(
                "SELECT descriptor FROM descriptor_links WHERE article_id=? "
                "ORDER BY descriptor",
                (identifier,),
            )
        ]
        raw = {
            "source": SOURCE,
            "source_id": identifier,
            "title": original["title"],
            "publication_date": publication,
            "abstract": abstract,
            "retrieved_at": processed,
            "access": "metadata_only",
        }
        # Stable source identity preserves articles sharing a DOI for later curation.
        result = curate([raw], "empirical")
        if result["quality"]["rejected_rows"]:
            raise AnalyticsError("research_invalid_article", identifier)
        doc = result["documents"][0]
        doc["keywords"] = keywords
        doi = None
        if _absent(original["doi"]):
            missing_doi += 1
        else:
            candidate = re.sub(
                r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)",
                "",
                unquote(original["doi"].strip()).lower(),
            )
            if re.fullmatch(r"10\.\d{4,9}/\S+", candidate):
                doi = candidate
            else:
                invalid_doi += 1
        doc["doi"] = doi
        doc["source_corpus_flag"] = original["corpus"]
        connection.execute(
            "INSERT INTO articles VALUES (?,?,?,?,?)",
            (
                identifier,
                publication,
                publication[:4],
                canonical_json(doc),
                canonical_json(original),
            ),
        )
        count += 1
        absent += abstract is None
        years[publication[:4]] += 1
        flags[original["corpus"]] += 1
        day_one += publication.endswith("-01")
        january_one += publication.endswith("-01-01")
    if not count:
        raise AnalyticsError("empty_corpus", "At least one article is required")
    return {
        "articles": count,
        "missing_abstracts": absent,
        "articles_by_year": dict(sorted(years.items())),
        "source_flags": dict(flags),
        "invalid_doi_syntax": invalid_doi,
        "missing_doi": missing_doi,
        "day_01_articles": day_one,
        "january_01_articles": january_one,
        "source_flags_applied_as_filter": False,
    }


def ingest_research(directory, database, *, approval_reference):
    """Publish a new snapshot atomically; leave sources/existing outputs untouched."""
    directory, database = Path(directory).resolve(), Path(database).resolve()
    repository = Path(__file__).resolve().parents[2]
    if (
        database.suffix != ".sqlite"
        or database.is_relative_to(directory)
        or database.is_relative_to(repository)
    ):
        raise AnalyticsError(
            "unsafe_corpus_destination", "Use external .sqlite storage"
        )
    if database.exists():
        raise AnalyticsError("corpus_destination_exists", "Choose a new snapshot path")
    if (
        not isinstance(approval_reference, str)
        or not approval_reference.strip()
        or len(approval_reference) > 2000
    ):
        raise AnalyticsError(
            "approval_reference_required", "Record the actual authorization reference"
        )
    before = _hashes(directory)
    descriptor, temporary = tempfile.mkstemp(
        prefix=".research-", suffix=".sqlite", dir=database.parent
    )
    os.close(descriptor)
    temporary = Path(temporary)
    old_limit = csv.field_size_limit()
    try:
        csv.field_size_limit(4 * 1024 * 1024)
        with closing(sqlite3.connect(temporary)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            files = _read_raw(connection, directory)
            links = _links(connection)
            processed = datetime.now(UTC).isoformat()
            summary = _documents(connection, processed)
            after = _hashes(directory)
            if before != after:
                raise AnalyticsError(
                    "corpus_source_changed", "Source changed during ingestion"
                )
            report = {
                "adapter_version": "centinela-eight-table-v1",
                "source": SOURCE,
                "source_sha256": before,
                "source_version": fingerprint(before),
                "source_files_unchanged": True,
                "processed_at": processed,
                "data_kind": "empirical",
                "use_scope": "research_authorized_as_declared",
                "approval_reference": approval_reference.strip(),
                "files": files,
                "relationships": links,
                **summary,
                "author_links": links["articles_authors"]["valid_distinct"],
                "descriptor_links": connection.execute(
                    "SELECT COUNT(*) FROM descriptor_links"
                ).fetchone()[0],
                "date_precision": "unverified",
                "coverage": "unverified_snapshot",
                "historical_availability": "unknown",
                "full_text_documents": 0,
                "descriptor_origin": "author_keywords_not_fitted_topics",
                "source_count_semantics": "preserved_not_inferred_from_exported_links",
                "keyword_name_mismatches": connection.execute(
                    "SELECT COUNT(*) FROM raw_articles_author_keywords l "
                    "JOIN raw_author_keywords k ON l.author_keyword_id=k.identifier "
                    "WHERE lower(trim(l.author_keyword))<>lower(trim(k.name))"
                ).fetchone()[0],
                "models_trained": False,
                "policy": (
                    "Research authorization is a caller reference, "
                    "not an inferred license. Raw rows remain intact. "
                    "Orphan/duplicate links are excluded only from query projections. "
                    "Local ingestion time is not historical availability. "
                    "Source flags/counts are preserved without invented semantics."
                ),
            }
            connection.execute("CREATE TABLE manifest (payload TEXT)")
            connection.execute(
                "INSERT INTO manifest VALUES (?)", (canonical_json(report),)
            )
            connection.commit()
        os.link(temporary, database)
        return report
    except (csv.Error, UnicodeError) as exc:
        raise AnalyticsError("corpus_encoding_or_csv", "Invalid UTF-8/CSV") from exc
    except sqlite3.IntegrityError as exc:
        raise AnalyticsError(
            "research_identity_conflict", "Repeated entity identifier"
        ) from exc
    finally:
        csv.field_size_limit(old_limit)
        temporary.unlink(missing_ok=True)
