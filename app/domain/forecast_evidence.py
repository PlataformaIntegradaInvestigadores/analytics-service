"""Paired evaluation of the frozen annual research forecasts."""

import math

from app.domain.annual_prediction import annual_rows, metrics
from app.domain.common import AnalyticsError


def _comparison(records):
    actual = [row["observed"] for row in records]
    ridge = metrics(actual, [row["prediction"] for row in records])
    reference = metrics(actual, [row["baseline_last_value"] for row in records])
    return {
        "ridge": ridge,
        "last_value": reference,
        "mae_difference": ridge["mae"] - reference["mae"],
        "rmse_difference": ridge["rmse"] - reference["rmse"],
    }


def _verify_records(records, expected):
    seen = set()
    for record in records:
        key = (record["topic_id"], record["year"])
        row = expected.get(key)
        if (
            key in seen
            or row is None
            or record["observed_through"] != row["observed_through"]
            or record["observed"] != row["observed"]
            or record["baseline_last_value"] != row["last_value"]
            or not math.isfinite(record["prediction"])
            or record["prediction"] < 0
        ):
            raise AnalyticsError(
                "forecast_series_mismatch",
                "Forecast records disagree with annual series",
            )
        seen.add(key)
    if seen != expected.keys():
        raise AnalyticsError("forecast_series_mismatch", "Incomplete forecast pairs")


def forecast_comparison(series, protocol, prediction):
    """Compare both methods on the same theme/year cells and validate cutoffs."""
    if not series:
        raise AnalyticsError("forecast_series_mismatch", "Annual series are missing")
    start, fit, validation, end = (
        protocol[field]
        for field in ("start_year", "topic_fit_end", "validation_end", "test_end")
    )
    rows = {}
    for topic, points in series.items():
        if [point["year"] for point in points] != list(range(start, end + 1)):
            raise AnalyticsError(
                "forecast_series_mismatch",
                "Expected annual coverage through the cutoff",
            )
        rows.update({(topic, row["year"]): row for row in annual_rows(points)})

    result = {}
    for name, lower, upper, group, summary in (
        ("validation", fit, validation, "validation_records", "validation"),
        ("diagnostic", validation, end, "test_records", "test"),
    ):
        records = prediction[group]
        _verify_records(
            records, {key: row for key, row in rows.items() if lower < key[1] <= upper}
        )
        comparison = _comparison(records)
        for method in ("ridge", "last_value"):
            if any(
                not math.isclose(
                    value,
                    prediction[summary][method][metric],
                    rel_tol=1e-10,
                    abs_tol=1e-10,
                )
                for metric, value in comparison[method].items()
            ):
                raise AnalyticsError(
                    "forecast_metric_mismatch",
                    "Stored metrics disagree with paired forecasts",
                )
        result[name] = {
            "start_year": lower + 1,
            "end_year": upper,
            "overall": comparison,
            "by_topic": {
                topic: _comparison([row for row in records if row["topic_id"] == topic])
                for topic in sorted(series)
            },
            "by_year": {
                str(year): _comparison([row for row in records if row["year"] == year])
                for year in range(lower + 1, upper + 1)
            },
        }
    _verify_records(
        prediction["forecasts"],
        {key: row for key, row in rows.items() if key[1] == end + 1},
    )
    return {
        **result,
        "unit": "articles_per_topic_year",
        "horizon_years": 1,
        "diagnostic_scope": "previously_observed_exploratory",
        "last_observed_year": end,
    }
