"""Predictor/explainer boundary checks, not claims of computed SHAP values."""

import math

from app.domain.common import AnalyticsError, fingerprint


def explanation_contract(
    *,
    model_id,
    features,
    row,
    prediction,
    target,
    training_features,
    method,
    model_family,
):
    supported = {
        "linear": {"linear_exact"},
        "tree": {"tree_shap"},
        "black_box": {"permutation", "kernel_shap"},
    }
    if (
        not model_id
        or not target
        or not features
        or len(set(features)) != len(features)
        or features != training_features
        or len(row) != len(features)
        or any(
            not isinstance(x, (int, float))
            or isinstance(x, bool)
            or not math.isfinite(x)
            for x in [*row, prediction]
        )
        or method not in supported.get(model_family, set())
    ):
        raise AnalyticsError(
            "incompatible_explainer",
            "Check model, ordered features, target and finite values",
        )
    content = {
        "model_id": model_id,
        "features": features,
        "row": row,
        "prediction": prediction,
        "target": target,
        "method": method,
        "model_family": model_family,
        "status": "compatible_not_explained",
    }
    return {"contract_id": fingerprint(content), **content}
