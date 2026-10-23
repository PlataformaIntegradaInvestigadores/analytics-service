"""Bounded CSV/JSONL import with explicit fields; no source/date guessing."""

import csv
import hashlib
import io
from pathlib import Path

from app.core.json_io import MAX_JSON_BYTES, decode_json
from app.domain.common import AnalyticsError, fingerprint
from app.domain.corpus import FIELDS, curate

REQUIRED = {"source", "source_id", "title", "retrieved_at"}


def field_dictionary() -> dict:
    return {
        "dictionary_version": "corpus-export-v1",
        "required": sorted(REQUIRED),
        "optional": sorted(FIELDS - REQUIRED),
        "date_fields": {
            "publication_date": "YYYY-MM-DD or null",
            "available_on": "YYYY-MM-DD or null",
            "retrieved_at": "timezone-aware ISO timestamp",
        },
        "keywords": (
            "JSON array of strings, including in CSV cells; no delimiter guessing"
        ),
        "access": ["unknown", "metadata_only", "open", "authorized"],
        "limits": {"bytes": MAX_JSON_BYTES, "rows": 1000},
        "policy": (
            "Explicit source fields only; unknown historical availability remains "
            "null; data_kind is caller-declared"
        ),
    }


def inspect_export(
    path: Path,
    file_format: str,
    data_kind: str,
    mapping: dict[str, str] | None = None,
    ignored_columns: list[str] | None = None,
    batch_size: int = 250,
) -> dict:
    if file_format not in ("csv", "jsonl"):
        raise AnalyticsError("invalid_export_format", "Use csv or jsonl explicitly")
    if (
        isinstance(batch_size, bool)
        or not isinstance(batch_size, int)
        or not 1 <= batch_size <= 1000
    ):
        raise AnalyticsError("invalid_batch_size", "Use 1..1000 rows per batch")
    mapping = (
        dict(mapping) if mapping is not None else {field: field for field in FIELDS}
    )
    ignored = set(ignored_columns or [])
    if (
        not set(mapping) <= FIELDS
        or not REQUIRED <= mapping.keys()
        or any(
            not isinstance(column, str) or not column.strip()
            for column in mapping.values()
        )
        or len(set(mapping.values())) != len(mapping)
        or set(mapping.values()) & ignored
    ):
        raise AnalyticsError(
            "invalid_field_mapping",
            "Map required canonical fields to unique, nonignored source columns",
        )
    with Path(path).open("rb") as stream:
        content = stream.read(MAX_JSON_BYTES + 1)
    if len(content) > MAX_JSON_BYTES:
        raise AnalyticsError(
            "input_too_large", "Export exceeds the bounded import limit"
        )
    try:
        text = content.decode("utf-8-sig")
        if file_format == "csv":
            reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
            headers = reader.fieldnames or []
            if (
                not headers
                or len(headers) != len(set(headers))
                or any(not field for field in headers)
            ):
                raise AnalyticsError(
                    "invalid_export", "CSV requires unique nonempty headers"
                )
            rows = []
            for row in reader:
                if None in row or any(value is None for value in row.values()):
                    raise AnalyticsError(
                        "invalid_export", "CSV row width disagrees with header"
                    )
                rows.append(row)
                if len(rows) > 1000:
                    raise AnalyticsError(
                        "export_row_limit",
                        "Split exports into files of at most 1000 rows",
                    )
        else:
            rows = []
            for line in text.splitlines():
                if not line.strip():
                    raise AnalyticsError(
                        "invalid_export", "Blank JSONL rows are ambiguous"
                    )
                row = decode_json(line.encode("utf-8"))
                if not isinstance(row, dict):
                    raise AnalyticsError(
                        "invalid_export", "Each JSONL row must be an object"
                    )
                rows.append(row)
                if len(rows) > 1000:
                    raise AnalyticsError(
                        "export_row_limit",
                        "Split exports into files of at most 1000 rows",
                    )
            headers = sorted({key for row in rows for key in row})
    except (UnicodeError, csv.Error) as exc:
        raise AnalyticsError(
            "invalid_export", "Invalid UTF-8 or CSV structure"
        ) from exc
    if not rows:
        raise AnalyticsError("empty_export", "Export contains no records")
    unknown = set(headers) - set(mapping.values()) - ignored
    missing = REQUIRED - {
        field for field, column in mapping.items() if column in headers
    }
    if unknown or missing:
        raise AnalyticsError(
            "incompatible_export_fields",
            "Explicitly map required fields and ignore or map extra columns",
        )
    records = []
    for row in rows:
        record = {
            field: row[column] for field, column in mapping.items() if column in row
        }
        if file_format == "csv":
            record = {
                key: None if value == "" else value for key, value in record.items()
            }
            if "keywords" in record:
                record["keywords"] = (
                    decode_json(record["keywords"].encode("utf-8"))
                    if record["keywords"] is not None
                    else []
                )
            # Blank optional access means unknown, not invented authorization.
            if record.get("access", "unknown") is None:
                record.pop("access")
        records.append(record)
    batch = {"records": records, "data_kind": data_kind}
    result = curate(**batch)
    manifest = {
        "import_version": "bounded-corpus-export-v1",
        "file_format": file_format,
        "input_sha256": hashlib.sha256(content).hexdigest(),
        "data_kind": data_kind,
        "mapping": mapping,
        "ignored_columns": sorted(ignored),
        "batch_size": batch_size,
        "batches": [
            {
                "offset": offset,
                "rows": len(records[offset : offset + batch_size]),
                "rows_sha256": fingerprint(records[offset : offset + batch_size]),
            }
            for offset in range(0, len(records), batch_size)
        ],
        "dataset_version": result["dataset_version"],
    }
    return {
        "status": (
            "compatible"
            if not result["quality"]["rejected_rows"]
            else "needs_correction"
        ),
        "manifest_id": fingerprint(manifest),
        "manifest": manifest,
        "field_dictionary": field_dictionary(),
        "observed_columns": sorted(headers),
        "missing_optional_fields": sorted(
            (FIELDS - REQUIRED)
            - {field for field, column in mapping.items() if column in headers}
        ),
        "batch": batch,
        "curation": result,
        "policy": (
            "Deduplication is file-wide, including across batch boundaries; "
            "completeness and cross-file conflicts are not independently verified"
        ),
    }
