"""Stateless orchestration; no database, framework or model-service dependency."""

from app.domain.common import AnalyticsError, next_month
from app.domain.comparison import compare_references
from app.domain.corpus import curate, temporal_split
from app.domain.features import historical_features
from app.domain.forecasting import backtest, reference_forecast
from app.domain.series import build_series
from app.domain.topics import build_catalog


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


def catalog_batch(payload: dict) -> dict:
    options = payload.copy()
    dataset = curate_batch(options.pop("batch"))
    return build_catalog(dataset, **options)


def catalog_series_batch(payload: dict) -> dict:
    catalog = catalog_batch(payload["catalog"])
    if (
        catalog["method"] == "topic_model"
        and catalog["fit_cutoff"] >= payload["start"] + "-01"
    ):
        raise AnalyticsError(
            "topic_temporal_leakage", "Thematic fit must precede the series window"
        )
    return aggregate_batch(
        {
            "batch": payload["catalog"]["batch"],
            "assignments": catalog["assignments"],
            "topic_ids": [topic["topic_id"] for topic in catalog["topics"]],
            "topic_definition_version": catalog["topic_definition_version"],
            "start": payload["start"],
            "end": payload["end"],
            "covered_periods": payload["covered_periods"],
        }
    )


def comparison_batch(payload: dict) -> dict:
    options, points, provenance = _prepare(payload)
    comparison = compare_references(points, **options)
    if comparison["common_origins"]:
        # A frozen retrospective series cannot pretend delayed records were known
        # at their original month end. Dynamic as-of reconstruction is future work.
        latest = comparison["common_origins"][-1]
        dataset = curate_batch(payload["series"]["batch"])
        for document in dataset["documents"]:
            publication = document["publication_date"]
            if publication is None:
                continue
            month = publication[:7]
            if payload["series"]["start"] <= month <= latest and (
                document["available_on"] is None
                or document["available_on"] >= next_month(month) + "-01"
            ):
                raise AnalyticsError(
                    "unverified_series_availability",
                    "Frozen monthly counts require known availability by their "
                    "month end; late arrivals need as-of reconstruction",
                )
    return {
        **comparison,
        **provenance,
        "availability_policy": "frozen_counts_known_by_publication_month_end",
    }
