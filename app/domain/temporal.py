"""Precision-aware periods; a date string never proves temporal precision."""

import re

from app.domain.common import AnalyticsError, parse_day

SCALE = {"year": 1, "quarter": 2, "month": 3, "day": 4}


def period(value: str, granularity: str, precision: str) -> str:
    if granularity not in SCALE or precision not in SCALE:
        raise AnalyticsError("unknown_precision", "Declare verified date precision")
    if SCALE[granularity] > SCALE[precision]:
        raise AnalyticsError("unsupported_precision", "Aggregation exceeds precision")
    day = parse_day(value)
    return {
        "year": f"{day.year:04d}",
        "quarter": f"{day.year:04d}-Q{(day.month - 1) // 3 + 1}",
        "month": value[:7],
        "day": value,
    }[granularity]


def next_period(value: str, granularity: str) -> str:
    patterns = {
        "year": r"[0-9]{4}",
        "quarter": r"[0-9]{4}-Q[1-4]",
        "month": r"[0-9]{4}-(0[1-9]|1[0-2])",
    }
    if granularity not in patterns or not re.fullmatch(patterns[granularity], value):
        raise AnalyticsError("invalid_period", "Invalid period or granularity")
    year = int(value[:4])
    if year == 0:
        raise AnalyticsError("invalid_period", "Year zero is not supported")
    step = {"year": 1, "quarter": 4, "month": 12}[granularity]
    index = 0 if step == 1 else int(value[-1:] if step == 4 else value[-2:]) - 1
    year, index = divmod(year * step + index + 1, step)
    if not 1 <= year <= 9999:
        raise AnalyticsError("invalid_period", "Calendar boundary exceeded")
    return (
        f"{year:04d}"
        if step == 1
        else f"{year:04d}-Q{index + 1}" if step == 4 else f"{year:04d}-{index + 1:02d}"
    )


def aggregate(documents, assignments, *, granularity, precision, complete_periods=()):
    """Observed snapshot counts, never silently turn unknown coverage into zero."""
    rows = {}
    identifiers = [d["document_id"] for d in documents]
    if len(identifiers) != len(set(identifiers)) or not set(assignments) <= set(
        identifiers
    ):
        raise AnalyticsError("invalid_assignment", "Unique known documents required")
    for doc in documents:
        key = period(doc["publication_date"], granularity, precision)
        entry = rows.setdefault(key, {"observed_documents": 0, "topics": {}})
        entry["observed_documents"] += 1
        if doc["document_id"] in assignments:
            topic = assignments[doc["document_id"]]
            entry["topics"][topic] = entry["topics"].get(topic, 0) + 1
    for key in complete_periods:
        next_period(key, granularity)
        rows.setdefault(key, {"observed_documents": 0, "topics": {}})
    return [
        {
            "period": key,
            **rows[key],
            "granularity": granularity,
            "precision": precision,
            "coverage": (
                "caller_declared_complete" if key in complete_periods else "unknown"
            ),
        }
        for key in sorted(rows)
    ]
