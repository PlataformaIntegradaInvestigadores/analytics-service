"""Bounded UTF-8 JSON decoding; ambiguous keys and nonfinite numbers are rejected."""

import json
import math
from pathlib import Path

from app.domain.common import AnalyticsError

MAX_JSON_BYTES = 8 * 1024 * 1024


def decode_json(payload: bytes):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise AnalyticsError("invalid_json", "Duplicate JSON object keys")
            result[key] = value
        return result

    def constant(value):
        raise AnalyticsError("invalid_json", "Nonfinite numbers are not valid JSON")

    def number(value):
        result = float(value)
        if not math.isfinite(result):
            constant(value)
        return result

    try:
        return json.loads(
            payload.decode("utf-8-sig"),
            object_pairs_hook=pairs,
            parse_constant=constant,
            parse_float=number,
        )
    except AnalyticsError:
        raise
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise AnalyticsError("invalid_json", "Invalid UTF-8 JSON content") from exc


def read_json_file(path: Path, max_bytes: int = MAX_JSON_BYTES):
    with path.open("rb") as stream:
        payload = stream.read(max_bytes + 1)
    if len(payload) > max_bytes:
        raise AnalyticsError(
            "input_too_large", "JSON file exceeds the configured byte limit"
        )
    return decode_json(payload)
