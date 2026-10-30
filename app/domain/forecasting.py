"""Auditable reference forecasts and rolling-origin technical evaluation."""

import math

from app.domain.common import AnalyticsError, fingerprint, next_month, parse_month

REFERENCE_VERSION = "reference-v1"


def _positive_integer(value, maximum: int) -> bool:
    return (
        isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= maximum
    )


def validate_points(points: list[dict]) -> None:
    if not 1 <= len(points) <= 240:
        raise AnalyticsError("invalid_history", "Provide 1..240 ordered monthly points")
    previous = None
    for point in points:
        period, value = point["period"], point["value"]
        parse_month(period)
        if previous is not None and period != next_month(previous):
            raise AnalyticsError(
                "irregular_series", "Months must be unique and contiguous"
            )
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not 0 <= value <= 1e12
        ):
            raise AnalyticsError(
                "invalid_value", "Counts must be finite and nonnegative"
            )
        previous = period


def reference_forecast(
    points: list[dict],
    cutoff: str,
    horizon: int,
    method: str = "last_value",
    season_length: int = 12,
) -> dict:
    validate_points(points)
    parse_month(cutoff)
    if not _positive_integer(horizon, 24) or not _positive_integer(season_length, 24):
        raise AnalyticsError("invalid_horizon", "Horizon and season must be 1..24")
    if method not in ("last_value", "seasonal_naive"):
        raise AnalyticsError("invalid_method", "Unknown reference method")
    history = [point for point in points if point["period"] <= cutoff]
    configuration = {
        "algorithm_version": REFERENCE_VERSION,
        "method": method,
        "season_length": season_length if method == "seasonal_naive" else None,
        "cutoff": cutoff,
        "horizon": horizon,
    }
    result = {
        **configuration,
        "history_sha256": fingerprint(history),
        "model_version": fingerprint({**configuration, "history": history}),
        "unit": "documents",
        "predictions": [],
        "status": "insufficient_data",
        "reason": None,
    }
    required = season_length if method == "seasonal_naive" else 1
    if not history or history[-1]["period"] != cutoff:
        result["reason"] = "cutoff_not_observed"
    elif len(history) < required or any(
        point["value"] is None for point in history[-required:]
    ):
        result["reason"] = "missing_required_history"
    else:
        result["status"] = "ok"
        window = history[-required:]
        result["predictions"] = [
            {
                "period": next_month(cutoff, step + 1),
                "value": float(window[step % required]["value"]),
            }
            for step in range(horizon)
        ]
    return result


def error_metrics(
    observed: list[float], predicted: list[float], training: list[float]
) -> dict:
    if not observed or len(observed) != len(predicted):
        raise AnalyticsError("invalid_metrics", "Provide nonempty paired observations")
    if any(
        isinstance(v, bool)
        or not isinstance(v, (int, float))
        or not math.isfinite(v)
        or not 0 <= v <= 1e12
        for v in observed + predicted + training
    ):
        raise AnalyticsError(
            "invalid_metrics", "Metrics require finite nonnegative counts"
        )
    absolute = [
        abs(actual - estimate)
        for actual, estimate in zip(observed, predicted, strict=True)
    ]
    mae = math.fsum(absolute) / len(absolute)
    volume = math.fsum(observed)
    scale = (
        math.fsum(
            abs(right - left)
            for left, right in zip(training, training[1:], strict=False)
        )
        / (len(training) - 1)
        if len(training) >= 2
        else 0
    )
    return {
        "n": len(observed),
        "mae": mae,
        "rmse": math.sqrt(
            math.fsum((a - p) ** 2 for a, p in zip(observed, predicted, strict=True))
            / len(observed)
        ),
        "wape": math.fsum(absolute) / volume if volume else None,
        "mase_lag1": mae / scale if scale else None,
        "undefined": [
            name
            for name, missing in (("wape", not volume), ("mase_lag1", not scale))
            if missing
        ],
    }


def backtest(
    points: list[dict],
    validation_start: str,
    validation_end: str,
    final_test_start: str,
    horizon: int = 1,
    min_train: int = 2,
    method: str = "last_value",
    season_length: int = 12,
) -> dict:
    validate_points(points)
    for period in (validation_start, validation_end, final_test_start):
        parse_month(period)
    if not validation_start <= validation_end < final_test_start:
        raise AnalyticsError(
            "invalid_validation", "Validation must precede reserved final test"
        )
    if not _positive_integer(min_train, 240):
        raise AnalyticsError(
            "invalid_training_window", "Training window must be 1..240"
        )
    # Validate model options even when no fold can be formed.
    reference_forecast(points, points[0]["period"], horizon, method, season_length)
    folds, skipped = [], []
    for index in range(len(points) - horizon):
        targets = points[index + 1 : index + 1 + horizon]
        if (
            targets[0]["period"] < validation_start
            or targets[-1]["period"] > validation_end
        ):
            continue
        history = points[: index + 1]
        reason = None
        if len(history) < min_train:
            reason = "short_training_window"
        elif any(point["value"] is None for point in history + targets):
            reason = "missing_observations"
        if reason:
            skipped.append({"cutoff": history[-1]["period"], "reason": reason})
            continue
        forecast = reference_forecast(
            history, history[-1]["period"], horizon, method, season_length
        )
        if forecast["status"] != "ok":
            skipped.append(
                {"cutoff": history[-1]["period"], "reason": forecast["reason"]}
            )
            continue
        observed = [float(point["value"]) for point in targets]
        predicted = [point["value"] for point in forecast["predictions"]]
        folds.append(
            {
                "cutoff": history[-1]["period"],
                "forecast": forecast,
                "observed": observed,
                "metrics": error_metrics(
                    observed, predicted, [float(p["value"]) for p in history]
                ),
            }
        )
    configuration = {
        "evaluation_version": "rolling-origin-v1",
        "method": method,
        "season_length": season_length,
        "validation_start": validation_start,
        "validation_end": validation_end,
        "final_test_start": final_test_start,
        "horizon": horizon,
        "min_train": min_train,
        # Reserved test values are excluded from evaluation identity and computations.
        "development_sha256": fingerprint(
            [p for p in points if p["period"] <= validation_end]
        ),
    }
    return {
        **configuration,
        "evaluation_id": fingerprint(configuration),
        "status": "ok" if folds else "insufficient_data",
        "folds": folds,
        "skipped": skipped,
        "test_policy": (
            "Final test excluded; overlapping horizons reported as separate origins"
        ),
    }
