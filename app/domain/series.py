"""Monthly hard-assignment series with explicitly declared coverage."""

from collections import Counter

from app.domain.common import AnalyticsError, fingerprint, next_month, parse_month


def build_series(
    dataset: dict,
    assignments: dict[str, str],
    topic_ids: list[str],
    topic_definition_version: str,
    start: str,
    end: str,
    covered_periods: list[str],
) -> dict:
    parse_month(start)
    parse_month(end)
    if start > end:
        raise AnalyticsError("invalid_window", "Start must not exceed end")
    periods = []
    current = start
    while current <= end:
        periods.append(current)
        if len(periods) > 240:
            raise AnalyticsError("window_limit", "At most 240 months per request")
        if current == end:
            break
        current = next_month(current)
    if not topic_ids or len(topic_ids) > 100 or len(topic_ids) != len(set(topic_ids)):
        raise AnalyticsError(
            "invalid_topics", "Declare 1..100 unique topic identifiers"
        )
    if not topic_definition_version.strip() or any(
        not topic.strip() for topic in topic_ids
    ):
        raise AnalyticsError(
            "invalid_topics", "Topic identifiers/version cannot be empty"
        )
    if len(covered_periods) != len(set(covered_periods)) or not set(
        covered_periods
    ) <= set(periods):
        raise AnalyticsError(
            "invalid_coverage", "Coverage must be unique months in the window"
        )
    known = {document["document_id"] for document in dataset["documents"]}
    if not set(assignments) <= known or not set(assignments.values()) <= set(topic_ids):
        raise AnalyticsError(
            "invalid_assignment", "Unknown document or topic assignment"
        )
    totals: Counter = Counter()
    assigned_totals: Counter = Counter()
    counts: Counter = Counter()
    missing_dates = outside_window = 0
    for document in dataset["documents"]:
        publication = document["publication_date"]
        if publication is None:
            missing_dates += 1
            continue
        period = publication[:7]
        if period not in periods:
            outside_window += 1
            continue
        totals[period] += 1
        topic = assignments.get(document["document_id"])
        if topic is not None:
            counts[topic, period] += 1
            assigned_totals[period] += 1
    covered = set(covered_periods)
    points = []
    for topic in sorted(topic_ids):
        for period in periods:
            complete = period in covered
            denominator = totals[period]
            points.append(
                {
                    "topic_id": topic,
                    "period": period,
                    "count": counts[topic, period] if complete else None,
                    "denominator": denominator if complete else None,
                    "share": (
                        counts[topic, period] / denominator
                        if complete and denominator
                        else None
                    ),
                    "assignment_coverage": (
                        assigned_totals[period] / denominator
                        if complete and denominator
                        else None
                    ),
                    "coverage": "declared_complete" if complete else "unknown",
                    "available_documents": denominator,
                }
            )
    configuration = {
        "series_algorithm": "monthly-hard-assignment-v1",
        "dataset_version": dataset["dataset_version"],
        "topic_definition_version": topic_definition_version,
        "topic_ids": sorted(topic_ids),
        "assignments": dict(sorted(assignments.items())),
        "start": start,
        "end": end,
        "covered_periods": sorted(covered_periods),
    }
    return {
        "series_version": fingerprint(configuration),
        **configuration,
        "data_kind": dataset["data_kind"],
        "unit": "documents",
        "points": points,
        "missing_date_documents": missing_dates,
        "outside_window_documents": outside_window,
        "coverage_evidence": (
            "Caller declaration; corpus completeness is not independently verified"
        ),
        "assignment_method": (
            "Provided single-topic assignments; no topic model fitted here"
        ),
    }
