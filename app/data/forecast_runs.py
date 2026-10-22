"""Local reference-run artifacts; loading never retrains or rewrites an artifact."""

import hashlib
import json
import platform
import sqlite3
from contextlib import closing
from importlib.metadata import version
from pathlib import Path

from pydantic import ValidationError

from app import __version__
from app.application.analysis import forecast_batch
from app.domain.common import AnalyticsError, canonical_json, fingerprint
from app.schemas.analytics import ForecastRequest, ForecastResult

ARTIFACT_VERSION = "reference-forecast-run-v1"
SOURCE_FILES = (
    "application/analysis.py",
    "data/forecast_runs.py",
    "domain/common.py",
    "domain/corpus.py",
    "domain/forecasting.py",
    "domain/series.py",
    "schemas/analytics.py",
)


def _build_artifact(payload: dict) -> dict:
    request = ForecastRequest.model_validate(payload).model_dump(mode="json")
    result = ForecastResult.model_validate(forecast_batch(request)).model_dump(
        mode="json"
    )
    source_root = Path(__file__).resolve().parents[1]
    return {
        "artifact_kind": "reference_forecast",
        "artifact_version": ARTIFACT_VERSION,
        "runtime": {
            "python": platform.python_version(),
            "service": __version__,
            "pydantic": version("pydantic"),
        },
        "code_sha256": {
            relative: hashlib.sha256((source_root / relative).read_bytes()).hexdigest()
            for relative in SOURCE_FILES
        },
        "request": request,
        "result": result,
    }


def _restore(payload: str, run_id: str) -> dict:
    try:
        artifact = json.loads(payload)
        if not isinstance(artifact, dict) or fingerprint(artifact) != run_id:
            raise ValueError("Artifact does not match its content identity")
        if artifact["artifact_version"] != ARTIFACT_VERSION:
            raise AnalyticsError(
                "unsupported_artifact_version", "Unsupported run format"
            )
        if (
            set(artifact)
            != {
                "artifact_kind",
                "artifact_version",
                "runtime",
                "code_sha256",
                "request",
                "result",
            }
            or artifact["artifact_kind"] != "reference_forecast"
        ):
            raise ValueError("Invalid artifact envelope")
        request = ForecastRequest.model_validate(artifact["request"]).model_dump(
            mode="json"
        )
        result = ForecastResult.model_validate(artifact["result"]).model_dump(
            mode="json"
        )
        if request != artifact["request"] or result != artifact["result"]:
            raise ValueError("Artifact contracts are not canonical")
        if (
            result["data_kind"] != request["series"]["batch"]["data_kind"]
            or result["topic_id"] != request["topic_id"]
            or result["cutoff"] != request["cutoff"]
            or result["horizon"] != request["horizon"]
            or result["method"] != request["method"]
            or result["topic_definition_version"]
            != request["series"]["topic_definition_version"]
        ):
            raise ValueError("Request and result provenance disagree")
    except AnalyticsError:
        raise
    except (ValueError, TypeError, KeyError, ValidationError) as exc:
        raise AnalyticsError(
            "forecast_run_corrupt", "Run integrity verification failed"
        ) from exc
    return {"run_id": run_id, **artifact}


class ForecastRunStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def save(self, payload: dict) -> dict:
        artifact = _build_artifact(payload)
        run_id = fingerprint(artifact)
        encoded = canonical_json(artifact)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS forecast_runs "
                "(run_id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
            )
            existing = connection.execute(
                "SELECT payload FROM forecast_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if existing and existing[0] != encoded:
                raise AnalyticsError(
                    "forecast_run_corrupt",
                    "Existing run differs from its content identity",
                )
            connection.execute(
                "INSERT OR IGNORE INTO forecast_runs VALUES (?, ?)", (run_id, encoded)
            )
        return _restore(encoded, run_id)

    def load(self, run_id: str) -> dict:
        if not self.path.is_file():
            raise AnalyticsError("forecast_run_not_found", "Database does not exist")
        uri = self.path.resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            table = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name = 'forecast_runs'"
            ).fetchone()
            if table is None:
                raise AnalyticsError(
                    "forecast_run_not_found", "No reference runs in database"
                )
            row = connection.execute(
                "SELECT payload FROM forecast_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if row is None:
                raise AnalyticsError("forecast_run_not_found", "Unknown run")
        return _restore(row[0], run_id)
