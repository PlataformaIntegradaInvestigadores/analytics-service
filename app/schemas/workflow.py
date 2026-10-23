"""Explicit preparation contracts for imports, topics, experiments and presentation."""

from typing import Any, Literal

from pydantic import Field, field_validator

from app.schemas.analytics import (
    BatchRequest,
    Contract,
    DataKind,
    ForecastResult,
    Prediction,
    QualityReport,
    SeriesPoint,
    SeriesRequest,
)


class Topic(Contract):
    topic_id: str = Field(min_length=1, max_length=256)
    label: str = Field(min_length=1, max_length=256)
    terms: list[str] = Field(min_length=1, max_length=100)

    @field_validator("terms")
    @classmethod
    def bounded_terms(cls, values):
        if any(not term.strip() or len(term) > 256 for term in values):
            raise ValueError("Terms require 1..256 nonblank characters")
        return values


class CatalogRequest(Contract):
    batch: BatchRequest
    topics: list[Topic] = Field(min_length=1, max_length=100)
    assignments: dict[str, str] = Field(max_length=1000)
    method: Literal["manual", "keywords", "topic_model"]
    model_version: str | None = Field(default=None, max_length=256)
    fit_document_ids: list[str] = Field(default_factory=list, max_length=1000)
    fit_cutoff: str | None = None


class CatalogResult(Contract):
    catalog_version: str
    catalog_algorithm: str
    topic_definition_version: str
    dataset_version: str
    data_kind: DataKind
    method: Literal["manual", "keywords", "topic_model"]
    model_version: str | None
    fit_document_ids: list[str]
    fit_cutoff: str | None
    fit_corpus_sha256: str | None
    topics: list[Topic]
    assignments: dict[str, str]
    unassigned_document_ids: list[str]
    evidence_status: str
    curation_quality: QualityReport


class CatalogSeriesRequest(Contract):
    catalog: CatalogRequest
    start: str
    end: str
    covered_periods: list[str] = Field(max_length=240)


class ComparisonRequest(Contract):
    series: SeriesRequest
    topic_id: str = Field(min_length=1, max_length=256)
    validation_start: str
    validation_end: str
    final_test_start: str
    horizon: int = Field(default=1, ge=1, le=24, strict=True)
    min_train: int = Field(default=2, ge=1, le=240, strict=True)
    season_length: int = Field(default=12, ge=1, le=24, strict=True)


class PairedMetrics(Contract):
    n: int
    mae: float | None
    rmse: float | None
    wape: float | None
    mean_fold_mase_lag1: float | None


class PairedFold(Contract):
    cutoff: str
    observed: list[float]
    predictions: dict[str, list[Prediction]]


class OmittedFolds(Contract):
    skipped: list[dict[str, str]]
    unpaired_origins: list[str]


class ComparisonResult(Contract):
    comparison_id: str
    comparison_algorithm: str
    configuration: dict[str, Any]
    development_sha256: str
    status: Literal["ok", "insufficient_data"]
    common_origins: list[str]
    paired_folds: list[PairedFold]
    metrics: dict[str, PairedMetrics]
    preferred_by_validation_mae: Literal["tie", "last_value", "seasonal_naive"] | None
    omitted: dict[str, OmittedFolds]
    test_policy: str
    availability_policy: str
    dataset_version: str
    series_version: str
    topic_definition_version: str
    topic_id: str
    data_kind: DataKind
    curation_quality: QualityReport


ExperimentKind = Literal["topic_catalog", "reference_forecast", "reference_comparison"]


class ExperimentRequest(Contract):
    kind: ExperimentKind
    request: dict[str, Any]
    parent_ids: list[str] = Field(default_factory=list, max_length=10)


class ExperimentArtifact(Contract):
    experiment_id: str
    artifact_version: Literal["analytics-experiment-v1"]
    kind: ExperimentKind
    request: dict[str, Any]
    result: CatalogResult | ForecastResult | ComparisonResult
    parent_ids: list[str]
    software: dict[str, Any]


class ExperimentSummary(Contract):
    experiment_id: str
    kind: ExperimentKind
    data_kind: DataKind
    dataset_version: str
    topic_id: str | None
    status: Literal["ok", "insufficient_data", "declared"]


class ExperimentPage(Contract):
    status: Literal["ok", "empty"]
    total: int
    offset: int
    limit: int
    items: list[ExperimentSummary]


class ExplanationState(Contract):
    experiment_id: str
    status: Literal["pending", "unavailable"]
    scope: Literal["local", "global"]
    reason: str
    model_version: str
    inputs_sha256: str
    predictions_sha256: str
    method: None
    attributions: list[dict[str, Any]]


class DashboardView(Contract):
    experiment_id: str
    status: Literal["ready", "insufficient_data", "empty"]
    data_kind: DataKind
    topic_id: str
    unit: Literal["documents"]
    cutoff: str
    dataset_version: str
    series_version: str
    topic_definition_version: str
    observed: list[SeriesPoint]
    forecast: list[Prediction]
    explanation: ExplanationState
    coverage_policy: str


class DashboardContract(Contract):
    contract_version: str
    unit: Literal["documents"]
    granularity: Literal["calendar_month"]
    filters: list[str]
    display_states: list[str]
    observed_forecast_policy: str
    null_policy: str
    xai_policy: str


class ExportDictionary(Contract):
    dictionary_version: str
    required: list[str]
    optional: list[str]
    date_fields: dict[str, str]
    keywords: str
    access: list[str]
    limits: dict[str, int]
    policy: str
