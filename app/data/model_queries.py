"""Read-only verified model metadata; never initializes or mutates a registry."""

import re

from pydantic import ValidationError

from app.core.json_io import decode_json
from app.data.documents import pagination, read_database
from app.domain.common import AnalyticsError, fingerprint
from app.schemas.models import ModelSummary


def summary(identifier, encoded):
    try:
        model = decode_json(encoded.encode("utf-8"))
        if (
            fingerprint(model) != identifier
            or model["format"] != "nmf-json-v1"
            or len(set(model["fit_ids"])) != len(model["fit_ids"])
        ):
            raise ValueError("Invalid model")
        result = ModelSummary.model_validate(
            {
                "model_id": identifier,
                "workset_id": model["workset_id"],
                "method": model["method"],
                "purpose": model["purpose"],
                "fit_document_count": len(model["fit_ids"]),
                "configuration": {
                    key: model["configuration"][key]
                    for key in ("topics", "seed", "max_features", "max_iter", "tol")
                },
                "versions": {
                    key: model["versions"][key]
                    for key in ("scikit-learn", "numpy", "scipy")
                },
                "cutoff": model["cutoff"],
                "temporal_status": model["temporal_status"],
            }
        )
        return result.model_dump()
    except (
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        ValidationError,
        AnalyticsError,
    ) as exc:
        raise AnalyticsError(
            "model_integrity", "Stored model failed integrity checks"
        ) from exc


def model_page(path, limit=20, offset=0):
    pagination(limit, offset)
    with read_database(path) as db:
        total = db.execute("SELECT COUNT(*) FROM fitted_models").fetchone()[0]
        rows = db.execute(
            "SELECT id,payload FROM fitted_models ORDER BY id LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        items = [summary(identifier, payload) for identifier, payload in rows]
    return {
        "status": "ok" if items else "empty",
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": items,
    }


def model_detail(path, identifier):
    if not re.fullmatch(r"[a-f0-9]{64}", identifier):
        raise AnalyticsError("invalid_model_id", "Use a SHA256 model ID")
    with read_database(path) as db:
        row = db.execute(
            "SELECT payload FROM fitted_models WHERE id=?", (identifier,)
        ).fetchone()
        if row is None:
            raise AnalyticsError("model_not_found", "Unknown model")
        return summary(identifier, row[0])
