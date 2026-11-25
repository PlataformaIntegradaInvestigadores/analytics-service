"""Annual snapshot forecasting and exact linear attributions on model output scale."""

import math

from app.domain.common import AnalyticsError, fingerprint

FEATURES = ["log1p_lag_1", "log1p_lag_2", "log1p_lag_3", "log1p_mean_previous_3"]


def annual_rows(points):
    if len(points) < 4 or len(points) > 200:
        raise AnalyticsError(
            "invalid_annual_series", "Provide 4..200 annual observations"
        )
    for i, point in enumerate(points):
        if (
            type(point["year"]) is not int
            or not 1 <= point["year"] <= 9998
            or (i and point["year"] != points[i - 1]["year"] + 1)
            or type(point["count"]) is not int
            or point["count"] < 0
        ):
            raise AnalyticsError(
                "invalid_annual_series", "Contiguous years and observed counts required"
            )
    rows = []
    for i in range(3, len(points) + 1):
        past = [points[i - j]["count"] for j in (1, 2, 3)]
        rows.append(
            {
                "year": points[i - 1]["year"] + 1,
                "observed_through": points[i - 1]["year"],
                "features": [math.log1p(v) for v in [*past, sum(past) / 3]],
                "observed": points[i]["count"] if i < len(points) else None,
                "last_value": past[0],
            }
        )
    return rows


def train_ridge(rows, alpha, reference=None):
    import numpy as np
    from sklearn.linear_model import Ridge

    if (
        len(rows) < 4
        or any(r["observed"] is None for r in rows)
        or not isinstance(alpha, (int, float))
        or isinstance(alpha, bool)
        or not math.isfinite(alpha)
        or alpha <= 0
    ):
        raise AnalyticsError(
            "invalid_regression", "Training rows and positive alpha required"
        )
    x = np.asarray([r["features"] for r in rows], dtype=float)
    y = np.log1p([r["observed"] for r in rows])
    if x.shape[1:] != (4,) or not np.isfinite(x).all() or not np.isfinite(y).all():
        raise AnalyticsError("invalid_regression", "Finite ordered features required")
    model = Ridge(alpha=alpha, solver="svd").fit(x, y)
    background = x.mean(axis=0).tolist() if reference is None else list(reference)
    if len(background) != 4 or not all(math.isfinite(v) for v in background):
        raise AnalyticsError(
            "invalid_background", "Four finite reference values required"
        )
    content = {
        "format": "annual-ridge-log1p-v1",
        "alpha": float(alpha),
        "features": FEATURES,
        "coefficients": model.coef_.tolist(),
        "intercept": float(model.intercept_),
        "background": background,
        "training_sha256": fingerprint(rows),
        "training_rows": len(rows),
        "trained_through": max(r["year"] for r in rows),
        "output_scale": "log1p_snapshot_article_count",
    }
    return {"model_id": fingerprint(content), **content}


def explain_prediction(model, row):
    if (
        model["features"] != FEATURES
        or len(row["features"]) != 4
        or row["year"] <= model["trained_through"]
        or row["observed_through"] >= row["year"]
        or not all(math.isfinite(v) for v in row["features"])
    ):
        raise AnalyticsError(
            "prediction_leakage_or_features",
            "Future target and ordered finite lags required",
        )
    content = {k: v for k, v in model.items() if k != "model_id"}
    if fingerprint(content) != model["model_id"]:
        raise AnalyticsError("model_integrity", "Regressor fingerprint mismatch")
    output = model["intercept"] + math.fsum(
        c * x for c, x in zip(model["coefficients"], row["features"], strict=True)
    )
    base = model["intercept"] + math.fsum(
        c * x for c, x in zip(model["coefficients"], model["background"], strict=True)
    )
    contributions = [
        c * (x - b)
        for c, x, b in zip(
            model["coefficients"], row["features"], model["background"], strict=True
        )
    ]
    if not math.isfinite(output) or output > 30:
        raise AnalyticsError(
            "forecast_out_of_bounds", "Unstable extrapolation rejected"
        )
    residual = abs(output - (base + math.fsum(contributions)))
    return {
        "year": row["year"],
        "observed": row["observed"],
        "prediction": max(0.0, math.expm1(output)),
        "baseline_last_value": row["last_value"],
        "model_id": model["model_id"],
        "observed_through": row["observed_through"],
        "explanation": {
            "method": "linear_exact",
            "scope": "local",
            "features": FEATURES,
            "feature_values": row["features"],
            "reference_values": model["background"],
            "base_value": base,
            "output_value": output,
            "contributions": contributions,
            "additivity_residual": residual,
            "output_scale": model["output_scale"],
            "count_transform": "max(0, expm1(output_value))",
            "interpretation": (
                "Algebraic feature attributions, not causal effects or SHAP. "
                "Contributions sum on log1p scale, not article units."
            ),
        },
    }


def metrics(actual, predicted):
    if (
        not actual
        or len(actual) != len(predicted)
        or any(not math.isfinite(v) or v < 0 for v in [*actual, *predicted])
    ):
        raise AnalyticsError(
            "invalid_metrics", "Paired finite nonnegative observations required"
        )
    errors = [a - p for a, p in zip(actual, predicted, strict=True)]
    return {
        "n": len(actual),
        "mae": math.fsum(abs(e) for e in errors) / len(errors),
        "rmse": math.sqrt(math.fsum(e * e for e in errors) / len(errors)),
    }
