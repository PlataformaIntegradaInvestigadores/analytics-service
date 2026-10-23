"""Read-only corpus queries and immutable prepared development working sets."""

import json
import os
import sqlite3
import tempfile
from collections import Counter
from contextlib import closing, contextmanager
from pathlib import Path

from app.core.provenance import source_files
from app.data.centinela import normalized
from app.domain.common import AnalyticsError, canonical_json, fingerprint
from app.domain.text import VERSION, prepare_text
from app.schemas.documents import Candidate, Preparation, TopicOutputs


@contextmanager
def read_database(path):
    path = Path(path)
    if not path.is_file():
        raise AnalyticsError("document_store_missing", "Configured snapshot is absent")
    with closing(
        sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    ) as connection:
        connection.execute("BEGIN")
        yield connection


def manifest(connection):
    return json.loads(connection.execute("SELECT payload FROM manifest").fetchone()[0])


def pagination(limit, offset):
    if (
        type(limit) is not int
        or not 1 <= limit <= 100
        or type(offset) is not int
        or not 0 <= offset <= 1000000
    ):
        raise AnalyticsError(
            "invalid_pagination", "Use limit 1..100 and offset 0..1000000"
        )


def article_page(
    path,
    *,
    limit=20,
    offset=0,
    year=None,
    has_abstract=None,
    author=None,
    descriptor=None,
):
    pagination(limit, offset)
    conditions, parameters = [], []
    if year is not None:
        if type(year) is not int or not 1 <= year <= 9999:
            raise AnalyticsError("invalid_year", "Use a complete year")
        conditions.append("a.year=?")
        parameters.append(str(year))
    if has_abstract is not None:
        if type(has_abstract) is not bool:
            raise AnalyticsError("invalid_filter", "has_abstract must be boolean")
        conditions.append("(json_extract(a.document,'$.abstract') IS NOT NULL)=?")
        parameters.append(int(has_abstract))
    for value, table, column in (
        (author, "author_links", "author_id"),
        (descriptor, "descriptor_links", "canonical"),
    ):
        if value is not None:
            if not isinstance(value, str) or not value.strip() or len(value) > 256:
                raise AnalyticsError("invalid_filter", "Use bounded nonblank filters")
            conditions.append(
                f"EXISTS (SELECT 1 FROM {table} l WHERE "
                f"l.article_id=a.article_id AND l.{column}=?)"
            )
            parameters.append(normalized(value) if column == "canonical" else value)
    where = " AND ".join(conditions) or "1=1"
    with read_database(path) as connection:
        total = connection.execute(
            "SELECT COUNT(*) FROM articles a WHERE " + where, parameters
        ).fetchone()[0]
        rows = connection.execute(
            "SELECT a.article_id,a.publication_date,a.document, "
            "(SELECT COUNT(*) FROM author_links l WHERE l.article_id=a.article_id), "
            "(SELECT COUNT(DISTINCT canonical) FROM descriptor_links l "
            "WHERE l.article_id=a.article_id) FROM articles a WHERE "
            + where
            + " ORDER BY a.article_id LIMIT ? OFFSET ?",
            [*parameters, limit, offset],
        ).fetchall()
    items = []
    for identifier, publication, encoded, authors, descriptors in rows:
        doc = json.loads(encoded)
        items.append(
            {
                "article_id": identifier,
                "title": doc["title"],
                "publication_date": publication,
                "has_abstract": doc["abstract"] is not None,
                "author_count": authors,
                "descriptor_count": descriptors,
            }
        )
    return {
        "status": "ok" if items else "empty",
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": items,
    }


def article_detail(path, identifier):
    with read_database(path) as connection:
        row = connection.execute(
            "SELECT document FROM articles WHERE article_id=?", (identifier,)
        ).fetchone()
        if row is None:
            raise AnalyticsError("article_not_found", "Unknown article")
        return {
            "article_id": identifier,
            "document": json.loads(row[0]),
            "authors": [
                r[0]
                for r in connection.execute(
                    "SELECT author_id FROM author_links "
                    "WHERE article_id=? ORDER BY author_id",
                    (identifier,),
                )
            ],
            "descriptors": [
                r[0]
                for r in connection.execute(
                    "SELECT descriptor FROM descriptor_links "
                    "WHERE article_id=? ORDER BY descriptor",
                    (identifier,),
                )
            ],
        }


def descriptor_page(path, limit=20, offset=0):
    pagination(limit, offset)
    with read_database(path) as connection:
        total = connection.execute(
            "SELECT COUNT(DISTINCT canonical) FROM descriptor_links"
        ).fetchone()[0]
        items = [
            {"descriptor": term, "articles": count}
            for term, count in connection.execute(
                "SELECT canonical,COUNT(DISTINCT article_id) AS n "
                "FROM descriptor_links GROUP BY canonical "
                "ORDER BY n DESC,canonical LIMIT ? OFFSET ?",
                (limit, offset),
            )
        ]
    return {
        "status": "ok" if items else "empty",
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": items,
    }


def summary(path):
    with read_database(path) as connection:
        report = manifest(connection)
    return {
        "status": "ready_for_development",
        "diagnostics": report,
        "training": "pending_use_clarification",
        "display_states": ["loading", "ready_for_development", "empty", "error"],
        "units": {
            "articles": "distinct_documents",
            "descriptor_counts": "distinct_documents_per_descriptor",
        },
        "policy": (
            "Source descriptors are not inferred topics; annual distributions "
            "describe this snapshot, not verified population trends"
        ),
    }


def _prepare(path, configuration, sink=None):
    config = Preparation.model_validate(configuration).model_dump()
    seen, retained, exclusions, groups = {}, [], [], {}
    with read_database(path) as connection:
        origin = manifest(connection)
        for identifier, year, encoded in connection.execute(
            "SELECT article_id,year,document FROM articles ORDER BY article_id"
        ):
            doc = json.loads(encoded)
            prepared = prepare_text(doc["title"], doc["abstract"])
            reason = None
            if not config["start_year"] <= int(year) <= config["end_year"]:
                reason = "outside_year_filter"
            elif (
                not prepared["has_abstract"] and config["missing_abstract"] == "exclude"
            ):
                reason = "missing_abstract"
            elif prepared["token_count"] < config["min_tokens"]:
                reason = "insufficient_tokens"
            if reason is None:
                key = prepared["duplicate_key"]
                groups.setdefault(key, []).append(identifier)
                if key in seen and config["duplicates"] == "exclude_later":
                    reason = "duplicate_text"
                else:
                    seen.setdefault(key, identifier)
            if reason:
                exclusions.append({"article_id": identifier, "reason": reason})
            else:
                record = {
                    "article_id": identifier,
                    "document": doc,
                    "prepared": prepared,
                }
                retained.append(
                    {"article_id": identifier, "record_sha256": fingerprint(record)}
                )
                if sink is not None:
                    sink.execute(
                        "INSERT INTO prepared VALUES (?,?)",
                        (identifier, canonical_json(record)),
                    )
    content = {
        "preparation_version": VERSION,
        "configuration": config,
        "source_version": origin["source_version"],
        "source_sha256": origin["source_sha256"],
        "source_processed_at": origin["processed_at"],
        "software_sha256": source_files(),
        "included": retained,
        "excluded": exclusions,
        "duplicate_groups": [values for values in groups.values() if len(values) > 1],
        "counts": {
            "included": len(retained),
            "excluded": len(exclusions),
            "exclusion_reasons": dict(Counter(item["reason"] for item in exclusions)),
        },
        "purpose": "development_working_set_not_final_temporal_partition",
        "training": "pending_use_clarification",
        "language": (
            "unknown; no language-specific stemming, lemmatization "
            "or stopword removal applied"
        ),
        "temporal_precision": "unverified",
    }
    return {"workset_id": fingerprint(content), **content}


def preview(path, configuration):
    return _prepare(path, configuration)


def save_workset(path, destination, configuration):
    path, destination = Path(path).resolve(), Path(destination).resolve()
    if destination == path or destination.exists() or destination.suffix != ".sqlite":
        raise AnalyticsError(
            "unsafe_workset_destination", "Choose a new external .sqlite path"
        )
    descriptor, name = tempfile.mkstemp(
        prefix=".workset-", suffix=".sqlite", dir=destination.parent
    )
    os.close(descriptor)
    temporary = Path(name)
    try:
        with closing(sqlite3.connect(temporary)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "CREATE TABLE prepared "
                "(article_id TEXT PRIMARY KEY,payload TEXT NOT NULL)"
            )
            connection.execute("CREATE TABLE manifest (payload TEXT NOT NULL)")
            result = _prepare(path, configuration, connection)
            connection.execute(
                "INSERT INTO manifest VALUES (?)", (canonical_json(result),)
            )
            connection.commit()
        os.link(temporary, destination)
        return result
    finally:
        temporary.unlink(missing_ok=True)


def working_manifest(path):
    with read_database(path) as connection:
        result = manifest(connection)
        content = {key: value for key, value in result.items() if key != "workset_id"}
        if result.get("workset_id") != fingerprint(content):
            raise AnalyticsError(
                "workset_corrupt", "Working-set manifest identity mismatch"
            )
        actual = {
            identifier: fingerprint(json.loads(payload))
            for identifier, payload in connection.execute(
                "SELECT article_id,payload FROM prepared"
            )
        }
        expected = {
            row["article_id"]: row["record_sha256"] for row in result["included"]
        }
        if actual != expected:
            raise AnalyticsError(
                "workset_corrupt", "Prepared records differ from manifest"
            )
        return result


def candidate_protocol(path, candidate):
    workset = working_manifest(path)
    candidate = Candidate.model_validate(candidate).model_dump()
    content = {
        "protocol_version": "topic-candidate-development-v1",
        "workset_id": workset["workset_id"],
        "candidate": candidate,
        "documents": workset["counts"]["included"],
        "training": "pending_use_clarification",
        "required_run_evidence": [
            "software_and_library_versions",
            "random_seed_if_applicable",
            "fitted_artifact_hash",
            "fit_document_ids",
            "feature_configuration",
            "assignments",
            "representative_terms",
            "representative_document_ids",
        ],
        "evaluation": {
            "structural": ["assignment_coverage", "topic_sizes", "term_diversity"],
            "pending": [
                "thematic_coherence",
                "empirical_topic_quality",
                "temporal_alignment",
            ],
        },
    }
    return {"protocol_id": fingerprint(content), **content}


def evaluate_outputs(path, payload):
    workset = working_manifest(path)
    outputs = TopicOutputs.model_validate(payload).model_dump()
    known = {row["article_id"] for row in workset["included"]}
    fit = outputs["fit_document_ids"]
    assignments, terms = outputs["assignments"], outputs["terms"]
    if (
        len(fit) != len(set(fit))
        or not set(fit) <= known
        or not set(assignments) <= known
        or not set(assignments.values()) <= terms.keys()
    ):
        raise AnalyticsError(
            "invalid_topic_outputs",
            "Unknown/duplicate fit documents or unknown assignments",
        )
    words = [word.strip().casefold() for values in terms.values() for word in values]
    if (
        not words
        or any(not values or len(values) > 100 for values in terms.values())
        or any(not word or len(word) > 256 for word in words)
    ):
        raise AnalyticsError(
            "invalid_topic_terms", "Supply bounded nonempty representative terms"
        )
    if any(
        len(set(word.strip().casefold() for word in values)) != len(values)
        for values in terms.values()
    ):
        raise AnalyticsError("invalid_topic_terms", "Repeated terms inside a topic")
    result = {
        "workset_id": workset["workset_id"],
        "model_version": outputs["model_version"],
        "outputs_sha256": fingerprint(outputs),
        "fit_document_ids": sorted(fit),
        "assignment_coverage": len(assignments) / len(known) if known else None,
        "unassigned_document_ids": sorted(known - set(assignments)),
        "topic_sizes": {
            topic: sum(value == topic for value in assignments.values())
            for topic in terms
        },
        "term_diversity": len(set(words)) / len(words),
        "coherence": None,
        "evidence": (
            "Structural checks of caller-provided outputs; "
            "no training or empirical model validation performed"
        ),
    }
    return {"evaluation_id": fingerprint(result), **result}
