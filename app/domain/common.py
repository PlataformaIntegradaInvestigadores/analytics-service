"""Framework-independent primitives shared by analytical use cases."""

import hashlib
import json
from datetime import date
from typing import Any


class AnalyticsError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def parse_day(value: str) -> date:
    try:
        result = date.fromisoformat(value)
        if result.isoformat() != value:
            raise ValueError
        return result
    except (ValueError, TypeError) as exc:
        raise AnalyticsError("invalid_date", "Use a complete YYYY-MM-DD date") from exc


def parse_month(value: str) -> date:
    return parse_day(value + "-01")


def next_month(value: str, steps: int = 1) -> str:
    day = parse_month(value)
    ordinal = day.year * 12 + day.month - 1 + steps
    year, month = divmod(ordinal, 12)
    if not 1 <= year <= 9999:
        raise AnalyticsError("invalid_period", "Period exceeds supported calendar")
    return f"{year:04d}-{month + 1:02d}"
