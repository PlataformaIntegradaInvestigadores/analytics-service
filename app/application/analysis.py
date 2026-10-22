"""Stateless orchestration; no database, framework or model-service dependency."""

from app.domain.common import AnalyticsError
from app.domain.corpus import curate, temporal_split
from app.domain.features import historical_features
from app.domain.forecasting import backtest, reference_forecast
from app.domain.series import build_series


def curate_batch(payload: dict) -> dict:
    return curate(**payload)


def split_batch(payload: dict) -> dict:
    options = payload.copy()
    dataset = curate_batch(options.pop("batch"))
    return {
        **temporal_split(dataset, **options),
        "curation_quality": dataset["quality"],
    }


def aggregate_batch(payload: dict) -> dict:
    options = payload.copy()
    dataset = curate_batch(options.pop("batch"))
    allow_rejected = options.pop("allow_rejected_records", False)
    if dataset["quality"]["rejected_rows"] and not allow_rejected:
        raise AnalyticsError(
            "rejected_records",
            "Resolve curation rejections or explicitly allow a partial dataset",
        )
    return {**build_series(dataset, **options), "curation_quality": dataset["quality"]}


def _prepare(payload: dict) -> tuple[dict, list[dict], dict]:
    options = payload.copy()
    series = aggregate_batch(options.pop("series"))
    topic = options.pop("topic_id")
    if topic not in series["topic_ids"]:
        raise AnalyticsError(
            "unknown_topic", "Topic is absent from the declared definition"
        )
    points = [
        {"period": point["period"], "value": point["count"]}
        for point in series["points"]
        if point["topic_id"] == topic
    ]
    provenance = {
        key: series[key]
        for key in (
            "dataset_version",
            "series_version",
            "topic_definition_version",
            "data_kind",
            "curation_quality",
        )
    }
    return options, points, {**provenance, "topic_id": topic}


def forecast_batch(payload: dict) -> dict:
    options, points, provenance = _prepare(payload)
    return {**reference_forecast(points, **options), **provenance}


def backtest_batch(payload: dict) -> dict:
    options, points, provenance = _prepare(payload)
    return {**backtest(points, **options), **provenance}


def features_batch(payload: dict) -> dict:
    options, points, provenance = _prepare(payload)
    return {**historical_features(points, **options), **provenance}
