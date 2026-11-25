"""Read-only corpus reconciliation and reviewable, non-destructive anomaly decisions."""

import json
from collections import Counter, defaultdict

from app.data.documents import read_database
from app.domain.common import AnalyticsError, fingerprint, parse_day
from app.domain.text import prepare_text


def audit_snapshot(corpus, prepared):
    doi_groups, text_groups, titles = (
        defaultdict(list),
        defaultdict(list),
        defaultdict(list),
    )
    years, flags, missing_by_flag = Counter(), Counter(), Counter()
    invalid_dates = day_one = january_one = missing_abstracts = 0
    with read_database(prepared) as work:
        selected = dict(work.execute("SELECT article_id,year FROM prepared"))
        assignments = dict(
            work.execute(
                "SELECT p.article_id,a.topic_id FROM prepared p JOIN assignments a "
                "ON p.document_id=a.document_id"
            )
        )
    with read_database(corpus) as db:
        origin = json.loads(db.execute("SELECT payload FROM manifest").fetchone()[0])
        if origin.get("use_scope") != "research_authorized_as_declared":
            raise AnalyticsError(
                "research_authorization_missing", "Research snapshot required"
            )
        rows = db.execute(
            "SELECT a.article_id,a.document,a.original,r._input_row FROM articles a "
            "JOIN raw_articles r ON a.article_id=r.identifier ORDER BY a.article_id"
        )
        count = 0
        for identifier, encoded, original, source_row in rows:
            doc, original = json.loads(encoded), json.loads(original)
            date = doc["publication_date"]
            try:
                parsed = parse_day(date)
                year = parsed.year
                years[year] += 1
                day_one += parsed.day == 1
                january_one += parsed.day == 1 and parsed.month == 1
            except AnalyticsError:
                invalid_dates += 1
                year = None
            prepared_text = prepare_text(doc["title"], doc["abstract"])
            absent = not prepared_text["has_abstract"]
            missing_abstracts += absent
            flags[original["corpus"]] += 1
            missing_by_flag[original["corpus"]] += absent
            record = {
                "article_id": identifier,
                "year": year,
                "publication_date": date,
                "title": doc["title"],
                "raw_file": "articles.csv",
                "raw_record": source_row,
                "included_in_previous_study": identifier in selected,
                "topic_id": assignments.get(identifier),
            }
            if doc["doi"]:
                doi_groups[doc["doi"]].append(record)
            if not absent:
                text_groups[prepared_text["duplicate_key"]].append(record)
            titles[fingerprint(" ".join(doc["title"].casefold().split()))].append(
                record
            )
            count += 1
        relationships = {}
        pairs = {
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
        for table, ((left, a), (right, b)) in pairs.items():
            total = db.execute(f"SELECT COUNT(*) FROM raw_{table}").fetchone()[0]
            joined = (
                f"FROM raw_{table} l JOIN raw_{a} a ON l.{left}=a.identifier "
                f"JOIN raw_{b} b ON l.{right}=b.identifier"
            )
            valid = db.execute("SELECT COUNT(*) " + joined).fetchone()[0]
            distinct = db.execute(
                f"SELECT COUNT(*) FROM (SELECT DISTINCT l.{left},l.{right} "
                + joined
                + ")"
            ).fetchone()[0]
            canonical = db.execute(f"SELECT COUNT(*) FROM valid_{table}").fetchone()[0]
            if distinct != canonical:
                raise AnalyticsError("relationship_reconciliation", table)
            relationships[table] = {
                "raw": total,
                "orphan_rows": total - valid,
                "repeated_valid_pairs": valid - distinct,
                "valid_distinct": distinct,
                "raw_equals_orphans_plus_repetitions_plus_valid": total
                == total - valid + valid - distinct + distinct,
            }
        count_mismatches = {}
        for field, table, column in (
            ("author_count", "articles_authors", "author_id"),
            ("affiliation_count", "articles_affiliations", "affiliation_id"),
        ):
            count_mismatches[field] = db.execute(
                f"SELECT COUNT(*) FROM raw_articles a LEFT JOIN "
                f"(SELECT article_id,COUNT(DISTINCT {column}) n FROM valid_{table} "
                "GROUP BY article_id) l ON a.identifier=l.article_id "
                f"WHERE CAST(a.{field} AS INTEGER)<>COALESCE(l.n,0)"
            ).fetchone()[0]
    cases, proposed_exclusions = [], set()
    for doi, values in sorted(doi_groups.items()):
        if len(values) < 2:
            continue
        conflict = len({r["year"] for r in values}) > 1
        kind = "doi_multiple_years" if conflict else "repeated_doi_review"
        content = {"kind": kind, "doi": doi, "records": values}
        cases.append(
            {
                "case_id": fingerprint(content),
                **content,
                "status": "pending_owner_review",
                "decision": None,
                "authority": None,
                "evidence_reference": None,
                "proposal": (
                    "quarantine sensitivity only; do not infer corrected year"
                    if conflict
                    else "check identity before any merge"
                ),
            }
        )
        if conflict:
            proposed_exclusions.update(r["article_id"] for r in values)
    impact = Counter(
        (selected[i], assignments.get(i)) for i in proposed_exclusions if i in selected
    )
    sensitivity = [
        {"year": year, "topic_id": topic, "removed_snapshot_documents": n}
        for (year, topic), n in sorted(impact.items(), key=lambda t: str(t[0]))
    ]
    actual_repeats = [v for v in text_groups.values() if len(v) > 1]
    summary = {
        "articles": count,
        "source_version": origin["source_version"],
        "source_sha256": origin["source_sha256"],
        "invalid_date_syntax": invalid_dates,
        "date_precision": "unverified; date syntax is not semantic precision",
        "day_one": day_one,
        "january_one": january_one,
        "years": dict(sorted(years.items())),
        "source_flags": dict(flags),
        "missing_abstracts_by_flag": dict(missing_by_flag),
        "missing_abstracts": missing_abstracts,
        "source_flag_policy": "not used as a filter",
        "doi_repeated_groups": len(cases),
        "doi_cross_year_groups": sum(c["kind"] == "doi_multiple_years" for c in cases),
        "exact_normalized_text_groups": len(actual_repeats),
        "exact_normalized_text_excess": sum(len(v) - 1 for v in actual_repeats),
        "normalized_title_repeat_groups": sum(len(v) > 1 for v in titles.values()),
        "declared_count_disagreements": count_mismatches,
        "count_interpretation": (
            "Source totals may differ from exported subset; not automatic" "ally errors"
        ),
        "relationships": relationships,
        "quarantine_sensitivity": {
            "candidate_source_records": len(proposed_exclusions),
            "affected_prepared_documents": sum(impact.values()),
            "changes_by_topic_year": sensitivity,
            "policy": (
                "Counts from excluding identified real records; no year corre"
                "cted and no data generated"
            ),
        },
        "owner_decisions_applied": False,
        "pending_questions": [
            "Meaning of corpus=True/False",
            "Universe of source author/affiliation counts",
            "Authoritative year for cross-year DOI cases",
            "Extraction date and temporal coverage",
        ],
    }
    private = {
        "doi_cases": cases,
        "exact_text_groups": actual_repeats,
        "candidate_quarantine_article_ids": sorted(proposed_exclusions),
    }
    return summary, private
