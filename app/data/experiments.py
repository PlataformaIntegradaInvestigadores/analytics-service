"""Local immutable analytical artifacts with lineage and bounded query pages."""

import sqlite3
from contextlib import closing
from pathlib import Path

from pydantic import ValidationError

from app.application import analysis
from app.application.presentation import dashboard_view
from app.core.json_io import MAX_JSON_BYTES, decode_json
from app.core.provenance import environment_manifest, verify_environment
from app.domain.common import AnalyticsError, canonical_json, fingerprint
from app.schemas.analytics import ForecastRequest, ForecastResult
from app.schemas.workflow import (
    CatalogRequest,
    CatalogResult,
    ComparisonRequest,
    ComparisonResult,
    ExperimentRequest,
)

VERSION = "analytics-experiment-v1"
KINDS = {
    "topic_catalog": (CatalogRequest, CatalogResult, analysis.catalog_batch),
    "reference_forecast": (ForecastRequest, ForecastResult, analysis.forecast_batch),
    "reference_comparison": (
        ComparisonRequest,
        ComparisonResult,
        analysis.comparison_batch,
    ),
}


def _summary(artifact: dict) -> dict:
    result = artifact["result"]
    return {
        "experiment_id": artifact["experiment_id"],
        "kind": artifact["kind"],
        "data_kind": result["data_kind"],
        "dataset_version": result["dataset_version"],
        "topic_id": result.get("topic_id"),
        "status": result.get("status", "declared"),
    }


def _restore(encoded: str, identifier: str) -> dict:
    try:
        if (
            not isinstance(encoded, str)
            or len(encoded.encode("utf-8")) > MAX_JSON_BYTES
        ):
            raise ValueError("Oversized artifact")
        content = decode_json(encoded.encode("utf-8"))
        if (
            set(content)
            != {
                "artifact_version",
                "kind",
                "request",
                "result",
                "parent_ids",
                "software",
            }
            or fingerprint(content) != identifier
            or content["artifact_version"] != VERSION
        ):
            raise ValueError("Invalid content identity or format")
        envelope = ExperimentRequest.model_validate(
            {key: content[key] for key in ("kind", "request", "parent_ids")}
        )
        request_schema, result_schema, _ = KINDS[envelope.kind]
        request = request_schema.model_validate(content["request"]).model_dump(
            mode="json"
        )
        result = result_schema.model_validate(content["result"]).model_dump(mode="json")
        if request != content["request"] or result != content["result"]:
            raise ValueError("Noncanonical analytical contracts")
        kind = (
            request["batch"]["data_kind"]
            if envelope.kind == "topic_catalog"
            else request["series"]["batch"]["data_kind"]
        )
        software = dict(content["software"])
        if (
            result["data_kind"] != kind
            or fingerprint(
                {
                    key: value
                    for key, value in software.items()
                    if key != "manifest_sha256"
                }
            )
            != software["manifest_sha256"]
        ):
            raise ValueError("Invalid data/software provenance")
        if len(envelope.parent_ids) != len(set(envelope.parent_ids)):
            raise ValueError("Duplicate parent links")
        if envelope.kind != "topic_catalog" and (
            result["topic_id"] != request["topic_id"]
            or result["topic_definition_version"]
            != request["series"]["topic_definition_version"]
        ):
            raise ValueError("Result topic disagrees with request")
        if envelope.kind == "reference_forecast" and any(
            result[key] != request[key] for key in ("cutoff", "horizon", "method")
        ):
            raise ValueError("Result configuration disagrees with request")
    except (ValueError, TypeError, KeyError, ValidationError) as exc:
        raise AnalyticsError(
            "experiment_corrupt", "Experiment identity or contracts are invalid"
        ) from exc
    return {"experiment_id": identifier, **content}


class ExperimentStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _read_connection(self):
        if not self.path.is_file():
            raise AnalyticsError("experiment_not_found", "No experiment database")
        return sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)

    @staticmethod
    def _has_table(connection) -> bool:
        return (
            connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='experiments'"
            ).fetchone()
            is not None
        )

    @staticmethod
    def _load(connection, identifier: str) -> dict:
        row = connection.execute(
            "SELECT payload FROM experiments WHERE experiment_id=?", (identifier,)
        ).fetchone()
        if row is None:
            raise AnalyticsError("experiment_not_found", "Unknown experiment")
        return _restore(row[0], identifier)

    def load(self, identifier: str) -> dict:
        with closing(self._read_connection()) as connection:
            if not self._has_table(connection):
                raise AnalyticsError("experiment_not_found", "No saved experiments")
            artifact = self._load(connection, identifier)
            self._check_metadata(connection, identifier, artifact)
            return artifact

    def replay(self, identifier: str) -> dict:
        artifact = self.load(identifier)
        software = verify_environment(artifact["software"])
        if software["status"] != "ok":
            return {
                "experiment_id": identifier,
                "status": "mismatch",
                "reason": "software_drift",
                "software": software,
                "recomputed": False,
            }
        _, result_schema, operation = KINDS[artifact["kind"]]
        current = result_schema.model_validate(
            operation(artifact["request"])
        ).model_dump(mode="json")
        equal = current == artifact["result"]
        return {
            "experiment_id": identifier,
            "status": "ok" if equal else "mismatch",
            "reason": None if equal else "result_mismatch",
            "software": software,
            "recomputed": True,
            "result_sha256": fingerprint(current),
            "expected_sha256": fingerprint(artifact["result"]),
            "scope": "Software reproducibility only; no empirical accuracy claim",
        }

    def dashboard(
        self, identifier: str, start: str | None = None, end: str | None = None
    ) -> dict:
        artifact = self.load(identifier)
        # Projection reconstructs historical counts from the saved request. Require
        # matching software before combining that reconstruction with saved output.
        if verify_environment(artifact["software"])["status"] != "ok":
            raise AnalyticsError(
                "experiment_software_drift",
                "Read the original artifact or reproduce its recorded environment "
                "before reconstructing a dashboard",
            )
        return dashboard_view(artifact, start, end)

    def save(self, payload: dict) -> dict:
        envelope = ExperimentRequest.model_validate(payload)
        request_schema, result_schema, operation = KINDS[envelope.kind]
        request = request_schema.model_validate(envelope.request).model_dump(
            mode="json"
        )
        if len(set(envelope.parent_ids)) != len(envelope.parent_ids):
            raise AnalyticsError("invalid_parent", "Parent identifiers must be unique")
        # Calculate only implemented algorithms; no caller-provided metrics/results.
        result = result_schema.model_validate(operation(request)).model_dump(
            mode="json"
        )
        content = {
            "artifact_version": VERSION,
            "kind": envelope.kind,
            "request": request,
            "result": result,
            "parent_ids": sorted(envelope.parent_ids),
            "software": environment_manifest(entry="requirements.txt"),
        }
        identifier, encoded = fingerprint(content), canonical_json(content)
        artifact = _restore(encoded, identifier)
        summary = _summary(artifact)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS experiments ("
                "experiment_id TEXT PRIMARY KEY, kind TEXT NOT NULL, "
                "data_kind TEXT NOT NULL, dataset_version TEXT NOT NULL, "
                "topic_id TEXT, status TEXT NOT NULL, payload TEXT NOT NULL)"
            )
            for parent_id in content["parent_ids"]:
                parent = self._load(connection, parent_id)
                self._check_metadata(connection, parent_id, parent)
                if any(
                    parent["result"][key] != result[key]
                    for key in ("dataset_version", "data_kind")
                ):
                    raise AnalyticsError(
                        "incompatible_parent",
                        "Lineage requires identical dataset version and data kind",
                    )
                if (
                    parent["kind"] == "topic_catalog"
                    and envelope.kind != "topic_catalog"
                    and parent["result"]["topic_definition_version"]
                    != result["topic_definition_version"]
                ):
                    raise AnalyticsError(
                        "incompatible_parent",
                        "Use the parent catalog thematic definition",
                    )
            existing = connection.execute(
                "SELECT payload FROM experiments WHERE experiment_id=?", (identifier,)
            ).fetchone()
            if existing and existing != (encoded,):
                raise AnalyticsError(
                    "experiment_corrupt", "Existing experiment content changed"
                )
            connection.execute(
                "INSERT OR IGNORE INTO experiments VALUES (?,?,?,?,?,?,?)",
                tuple(
                    summary[key]
                    for key in (
                        "experiment_id",
                        "kind",
                        "data_kind",
                        "dataset_version",
                        "topic_id",
                        "status",
                    )
                )
                + (encoded,),
            )
            persisted = self._load(connection, identifier)
            self._check_metadata(connection, identifier, persisted)
            if persisted != artifact:
                raise AnalyticsError(
                    "experiment_corrupt", "Experiment changed during persistence"
                )
        return artifact

    @staticmethod
    def _check_metadata(connection, identifier, artifact):
        row = connection.execute(
            "SELECT kind,data_kind,dataset_version,topic_id,status "
            "FROM experiments WHERE experiment_id=?",
            (identifier,),
        ).fetchone()
        expected = _summary(artifact)
        if row != tuple(
            expected[key]
            for key in ("kind", "data_kind", "dataset_version", "topic_id", "status")
        ):
            raise AnalyticsError(
                "experiment_corrupt", "Experiment index disagrees with its artifact"
            )

    def query(self, *, limit: int = 20, offset: int = 0, **filters) -> dict:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 100
            or isinstance(offset, bool)
            or not isinstance(offset, int)
            or not 0 <= offset <= 1000000
        ):
            raise AnalyticsError(
                "invalid_pagination", "Use limit 1..100 and offset 0..1000000"
            )
        if set(filters) - {"kind", "data_kind", "topic_id", "status"}:
            raise AnalyticsError("invalid_filter", "Unsupported experiment filter")
        selected = {key: value for key, value in filters.items() if value is not None}
        allowed = {
            "kind": set(KINDS),
            "data_kind": {"synthetic", "empirical"},
            "status": {"ok", "insufficient_data", "declared"},
        }
        if any(
            not isinstance(value, str)
            or not value.strip()
            or len(value) > 256
            or key in allowed
            and value not in allowed[key]
            for key, value in selected.items()
        ):
            raise AnalyticsError("invalid_filter", "Invalid experiment filter value")
        where = " AND ".join(f"{key}=?" for key in sorted(selected)) or "1=1"
        parameters = tuple(selected[key] for key in sorted(selected))
        page = {
            "status": "empty",
            "total": 0,
            "offset": offset,
            "limit": limit,
            "items": [],
        }
        if not self.path.is_file():
            return page
        with closing(self._read_connection()) as connection:
            connection.execute("BEGIN")
            if not self._has_table(connection):
                return page
            total = connection.execute(
                "SELECT COUNT(*) FROM experiments WHERE " + where, parameters
            ).fetchone()[0]
            rows = connection.execute(
                "SELECT experiment_id,payload FROM experiments WHERE "
                + where
                + " ORDER BY experiment_id LIMIT ? OFFSET ?",
                parameters + (limit, offset),
            ).fetchall()
            items = []
            for identifier, encoded in rows:
                artifact = _restore(encoded, identifier)
                self._check_metadata(connection, identifier, artifact)
                items.append(_summary(artifact))
        return {
            **page,
            "status": "ok" if items else "empty",
            "total": total,
            "items": items,
        }
