import pytest

from app.application.analysis import features_batch
from app.domain.common import AnalyticsError
from app.domain.features import historical_features


def history(values):
    return [
        {"period": f"2020-{i:02d}", "value": value} for i, value in enumerate(values, 1)
    ]


def test_historical_features_never_include_the_target_or_future():
    result = historical_features(history([2, 4, 6, 8]), [1, 2], [2])
    changed = historical_features(history([2, 4, 900, 999]), [1, 2], [2])
    third = result["rows"][2]
    assert third["features"] == {"lag_1": 4, "lag_2": 2, "mean_2": 3}
    assert third["features"] == changed["rows"][2]["features"]
    assert third["target_value"] == 6
    assert third["observed_through"] == "2020-02"
    assert third["complete_features"]
    inference = result["rows"][-1]
    assert inference["target_period"] == "2020-05"
    assert inference["target_value"] is None
    assert inference["features"] == {"lag_1": 8, "lag_2": 6, "mean_2": 7}
    assert result["rows"][0]["observed_through"] is None
    assert not result["rows"][0]["complete_features"]


def test_missing_history_remains_explicit():
    result = historical_features(history([2, None, 6]), [1], [2])
    assert result["rows"][2]["features"] == {"lag_1": None, "mean_2": None}
    assert result["rows"][-1]["features"] == {"lag_1": 6, "mean_2": None}


@pytest.mark.parametrize(
    "lags,windows",
    [
        ([], []),
        ([0], []),
        ([25], []),
        ([1, 1], []),
        ([True], []),
        ([1.5], []),
        ([], [0]),
        ([], [2, 2]),
    ],
)
def test_invalid_feature_configuration(lags, windows):
    with pytest.raises(AnalyticsError):
        historical_features(history([1, 2]), lags, windows)


def test_feature_use_case_has_full_lineage(series_request):
    result = features_batch(
        {
            "series": series_request,
            "topic_id": "topic-a",
            "lags": [1],
            "rolling_windows": [2],
        }
    )
    assert result["data_kind"] == "synthetic"
    assert result["rows"][-1]["target_value"] is None
    assert result["rows"][-1]["features"] == {"lag_1": 6, "mean_2": 5.5}
