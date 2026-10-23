"""One-step features: each row sees observations strictly before its target."""

import math

from app.domain.common import AnalyticsError, fingerprint, next_month
from app.domain.forecasting import validate_points


def historical_features(
    points: list[dict], lags: list[int], rolling_windows: list[int]
) -> dict:
    validate_points(points)
    for options in (lags, rolling_windows):
        if len(options) != len(set(options)) or any(
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 1 <= value <= 24
            for value in options
        ):
            raise AnalyticsError(
                "invalid_features", "Use unique integer lookbacks in 1..24"
            )
    if not lags and not rolling_windows:
        raise AnalyticsError(
            "invalid_features", "Declare at least one historical feature"
        )
    ordered = [*points, {"period": next_month(points[-1]["period"]), "value": None}]
    rows = []
    for index, point in enumerate(ordered):
        features = {
            f"lag_{lag}": ordered[index - lag]["value"] if index >= lag else None
            for lag in sorted(lags)
        }
        for window in sorted(rolling_windows):
            values = [p["value"] for p in ordered[max(0, index - window) : index]]
            features[f"mean_{window}"] = (
                math.fsum(values) / window
                if len(values) == window and all(value is not None for value in values)
                else None
            )
        rows.append(
            {
                "target_period": point["period"],
                "target_value": point["value"],
                "observed_through": ordered[index - 1]["period"] if index else None,
                "features": features,
                "complete_features": all(v is not None for v in features.values()),
            }
        )
    configuration = {
        "feature_algorithm": "one-step-history-v1",
        "lags": sorted(lags),
        "rolling_windows": sorted(rolling_windows),
        "history_sha256": fingerprint(points),
    }
    return {
        **configuration,
        "feature_version": fingerprint(configuration),
        "rows": rows,
        "usage_policy": (
            "Target excluded from its features. Split rows temporally before fitting; "
            "no learned transformation is fitted here. "
            "Last row is next-period inference."
        ),
    }
