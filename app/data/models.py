"""Content-addressed inert JSON models; never load executable pickle/joblib."""

import json
import re
import sqlite3
from contextlib import closing

from app.core.json_io import MAX_JSON_BYTES, decode_json
from app.domain.common import AnalyticsError, canonical_json, fingerprint


class ModelStore:
    def __init__(self, path):
        self.path = path
        with closing(sqlite3.connect(path)) as db, db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS fitted_models "
                "(id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
            )

    def save(self, artifact):
        content = {k: v for k, v in artifact.items() if k != "model_id"}
        encoded = canonical_json(content)
        if (
            artifact.get("format") != "nmf-json-v1"
            or artifact.get("purpose") != "technical"
            or fingerprint(content) != artifact.get("model_id")
            or len(encoded.encode()) > MAX_JSON_BYTES
        ):
            raise AnalyticsError(
                "invalid_model", "Expected bounded verified technical NMF JSON"
            )
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                "INSERT OR IGNORE INTO fitted_models VALUES (?,?)",
                (artifact["model_id"], encoded),
            )
        return self.load(artifact["model_id"])

    def load(self, identifier):
        if not re.fullmatch(r"[a-f0-9]{64}", identifier):
            raise AnalyticsError("invalid_model_id", "Use a SHA256 model ID")
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute(
                "SELECT payload FROM fitted_models WHERE id=?", (identifier,)
            ).fetchone()
        if row is None:
            raise AnalyticsError("model_not_found", "Unknown model")
        try:
            content = decode_json(row[0].encode())
            if fingerprint(content) != identifier:
                raise ValueError("Fingerprint mismatch")
        except (ValueError, json.JSONDecodeError) as exc:
            raise AnalyticsError("model_integrity", "Corrupt model") from exc
        return {"model_id": identifier, **content}
