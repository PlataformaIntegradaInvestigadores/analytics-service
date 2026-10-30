import copy
import math

import pytest

from app.application.analysis import (
    aggregate_batch,
    backtest_batch,
    forecast_batch,
    split_batch,
)
from app.domain.common import AnalyticsError
from app.domain.corpus import curate
from app.domain.forecasting import backtest, error_metrics, reference_forecast
from app.domain.series import build_series


def points(values):
    return [
        {"period": f"2020-{i:02d}", "value": value} for i, value in enumerate(values, 1)
    ]


def test_monthly_counts_shares_zero_and_unknown_coverage(series_request):
    request = copy.deepcopy(series_request)
    request["covered_periods"].remove("2020-03")
    result = aggregate_batch(request)
    rows = {(p["topic_id"], p["period"]): p for p in result["points"]}
    assert rows["topic-a", "2020-02"]["count"] == 2
    assert rows["topic-a", "2020-02"]["denominator"] == 2
    assert rows["topic-a", "2020-02"]["share"] == 1
    assert rows["topic-b", "2020-02"]["count"] == 0
    assert rows["topic-b", "2020-02"]["share"] == 0
    assert rows["topic-a", "2020-03"]["count"] is None
    assert rows["topic-a", "2020-03"]["denominator"] is None
    assert rows["topic-a", "2020-03"]["available_documents"] == 3
    assert result["data_kind"] == "synthetic"
    assert "no topic model" in result["assignment_method"]
    reordered = copy.deepcopy(request)
    reordered["topic_ids"].reverse()
    reordered["covered_periods"].reverse()
    assert aggregate_batch(reordered)["series_version"] == result["series_version"]
    request["topic_definition_version"] = "another-fixed-vocabulary"
    assert aggregate_batch(request)["series_version"] != result["series_version"]


def test_denominator_includes_unassigned_and_empty_month_is_not_division_by_zero(
    record,
):
    dataset = curate(
        [
            record(),
            record("two"),
            record("undated", publication_date=None),
            record("outside", publication_date="2019-12-01"),
        ],
        "synthetic",
    )
    result = build_series(
        dataset,
        {"doi:10.9999/synthetic-one": "a"},
        ["a"],
        "fixed-v1",
        "2020-01",
        "2020-02",
        ["2020-01", "2020-02"],
    )
    jan, feb = result["points"]
    assert jan["count"] == 1 and jan["denominator"] == 2
    assert jan["share"] == jan["assignment_coverage"] == 0.5
    assert feb["count"] == feb["denominator"] == 0
    assert feb["share"] is None and feb["assignment_coverage"] is None
    assert result["missing_date_documents"] == result["outside_window_documents"] == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"start": "2020-07"},
        {"start": "1990-01"},
        {"start": "bad"},
        {"topic_ids": ["topic-a", "topic-a"]},
        {"topic_ids": []},
        {"topic_definition_version": " "},
        {"topic_ids": [" "]},
        {"covered_periods": ["2020-01", "2020-01"]},
        {"covered_periods": ["2019-12"]},
        {"assignments": {"unknown": "topic-a"}},
        {"assignments": {"doi:10.9999/synthetic-1-0": "unknown"}},
    ],
)
def test_series_invalid_inputs(series_request, overrides):
    with pytest.raises(AnalyticsError):
        aggregate_batch({**series_request, **overrides})


def test_partial_curation_requires_explicit_opt_in(series_request, record):
    series_request["batch"]["records"].append(record("bad", publication_date="2020"))
    with pytest.raises(AnalyticsError, match="rejections"):
        aggregate_batch(series_request)
    result = aggregate_batch({**series_request, "allow_rejected_records": True})
    assert result["curation_quality"]["rejected_rows"] == 1


def test_last_value_ignores_future_values_and_is_deterministic():
    original = points([2, 4, 6, 900, 800])
    changed = points([2, 4, 6, 1, 2])
    result = reference_forecast(original, "2020-03", 3)
    assert result == reference_forecast(changed, "2020-03", 3)
    assert result["predictions"] == [
        {"period": "2020-04", "value": 6.0},
        {"period": "2020-05", "value": 6.0},
        {"period": "2020-06", "value": 6.0},
    ]
    assert result["status"] == "ok"
    assert reference_forecast(points([None, 4]), "2020-02", 1)["status"] == "ok"


def test_seasonal_reference_cycles_observed_history():
    result = reference_forecast(points([1, 7, 2, 8]), "2020-04", 5, "seasonal_naive", 2)
    assert [p["value"] for p in result["predictions"]] == [2, 8, 2, 8, 2]


@pytest.mark.parametrize(
    "values,cutoff,method,season,reason",
    [
        ([1, 2], "2019-12", "last_value", 12, "cutoff_not_observed"),
        ([1, 2], "2020-03", "last_value", 12, "cutoff_not_observed"),
        ([1, None], "2020-02", "last_value", 12, "missing_required_history"),
        ([1, 2], "2020-02", "seasonal_naive", 12, "missing_required_history"),
        ([None, 2], "2020-02", "seasonal_naive", 2, "missing_required_history"),
    ],
)
def test_insufficient_data_is_explicit(values, cutoff, method, season, reason):
    result = reference_forecast(points(values), cutoff, 1, method, season)
    assert result["status"] == "insufficient_data"
    assert result["reason"] == reason
    assert result["predictions"] == []


@pytest.mark.parametrize(
    "history,kwargs",
    [
        ([], {}),
        (points([True]), {}),
        (points([-1]), {}),
        (points([float("inf")]), {}),
        (points([float("nan")]), {}),
        (points(["one"]), {}),
        (points([1e13]), {}),
        ([{"period": "2020-01", "value": 1}, {"period": "2020-03", "value": 1}], {}),
        ([{"period": "2020-01", "value": 1}] * 2, {}),
        (points([1]), {"horizon": 0}),
        (points([1]), {"season_length": 0}),
        (points([1]), {"method": "invented"}),
    ],
)
def test_invalid_forecast_inputs(history, kwargs):
    with pytest.raises(AnalyticsError):
        reference_forecast(history, "2020-01", **{"horizon": 1, **kwargs})


def test_metrics_known_results_and_undefined_cases():
    result = error_metrics([3, 6], [2, 4], [1, 2, 4])
    assert result["n"] == 2
    assert result["mae"] == 1.5
    assert result["rmse"] == pytest.approx(math.sqrt(2.5))
    assert result["wape"] == pytest.approx(1 / 3)
    assert result["mase_lag1"] == 1
    undefined = error_metrics([0], [0], [2, 2])
    assert undefined["wape"] is None and undefined["mase_lag1"] is None
    assert undefined["undefined"] == ["wape", "mase_lag1"]
    assert error_metrics([1], [2], [1])["mase_lag1"] is None


@pytest.mark.parametrize(
    "observed,predicted,training",
    [
        ([], [], []),
        ([1], [1, 2], [1]),
        ([float("nan")], [1], [1]),
        ([1], [-1], [1]),
        ([1], [1], [float("inf")]),
    ],
)
def test_metrics_reject_incomparable_or_nonfinite_values(observed, predicted, training):
    with pytest.raises(AnalyticsError):
        error_metrics(observed, predicted, training)


def test_rolling_origins_exclude_reserved_final_test():
    result = backtest(points([1, 2, 3, 4, 5, 600]), "2020-03", "2020-05", "2020-06")
    changed = backtest(points([1, 2, 3, 4, 5, 1]), "2020-03", "2020-05", "2020-06")
    assert result == changed
    assert result["status"] == "ok" and len(result["folds"]) == 3
    for fold in result["folds"]:
        assert fold["metrics"]["mae"] == fold["metrics"]["rmse"] == 1
        assert fold["metrics"]["mase_lag1"] == 1
        assert all(p["period"] < "2020-06" for p in fold["forecast"]["predictions"])


def test_backtest_skips_short_missing_and_seasonally_insufficient_folds():
    short = backtest(points([1, 2, 3]), "2020-02", "2020-03", "2020-04", min_train=3)
    assert short["status"] == "insufficient_data"
    assert short["skipped"][0]["reason"] == "short_training_window"
    missing = backtest(points([1, None, 3, 4]), "2020-03", "2020-04", "2020-05")
    assert missing["skipped"][0]["reason"] == "missing_observations"
    seasonal = backtest(
        points([1, 2, 3, 4]), "2020-03", "2020-04", "2020-05", method="seasonal_naive"
    )
    assert seasonal["skipped"][0]["reason"] == "missing_required_history"


@pytest.mark.parametrize(
    "overrides",
    [
        {"validation_start": "2020-05", "validation_end": "2020-03"},
        {"final_test_start": "2020-04"},
        {"min_train": 0},
        {"horizon": 0},
    ],
)
def test_backtest_configuration_validation(overrides):
    options = {
        "validation_start": "2020-03",
        "validation_end": "2020-04",
        "final_test_start": "2020-05",
        **overrides,
    }
    with pytest.raises(AnalyticsError):
        backtest(points([1, 2, 3, 4, 5]), **options)


def test_end_to_end_use_cases_carry_dataset_topic_and_series_versions(
    batch, series_request
):
    split = split_batch(
        {
            "batch": batch,
            "train_end": "2020-01-31",
            "validation_end": "2020-02-29",
            "test_end": "2020-03-31",
        }
    )
    assert split["curation_quality"]["input_rows"] == 1
    payload = {"series": series_request, "topic_id": "topic-a"}
    forecast = forecast_batch({**payload, "cutoff": "2020-05", "horizon": 2})
    evaluation = backtest_batch(
        {
            **payload,
            "validation_start": "2020-03",
            "validation_end": "2020-05",
            "final_test_start": "2020-06",
        }
    )
    for key in (
        "dataset_version",
        "series_version",
        "topic_definition_version",
        "data_kind",
    ):
        assert forecast[key] == evaluation[key]
    assert forecast["predictions"][0]["value"] == 5
    with pytest.raises(AnalyticsError, match="absent"):
        forecast_batch(
            {**payload, "topic_id": "unknown", "cutoff": "2020-05", "horizon": 1}
        )
