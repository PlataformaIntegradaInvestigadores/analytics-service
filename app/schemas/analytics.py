"""HTTP/CLI contracts; validation never claims empirical completeness."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool

Period = str
DataKind = Literal["synthetic", "empirical"]
Lookback = Annotated[int, Field(ge=1, le=24, strict=True)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BatchRequest(Contract):
    """Raw rows are checked individually; failures appear in the quality report.

    Required nonempty text: source, source_id, title, retrieved_at.
    retrieved_at is an ISO timestamp with timezone. Optional publication_date
    and available_on require complete YYYY-MM-DD dates; unknown dates stay null.
    Optional text: doi, abstract, language (2/3 letters), full_text, rights_note.
    keywords is an optional list of strings. access is unknown (default),
    metadata_only, open or authorized. Full text needs open/authorized access
    and a nonempty rights_note. Unknown fields are rejected per row.
    data_kind is a caller declaration, not independently verified evidence.
    """

    data_kind: DataKind
    records: list[dict[str, Any]] = Field(
        max_length=1000,
        description=(
            "Uncurated objects; rejected rows retain their zero-based row index."
        ),
    )


class SplitRequest(Contract):
    batch: BatchRequest
    train_end: str
    validation_end: str
    test_end: str
    availability_policy: Literal["verified", "publication_date_proxy"] = "verified"


class SeriesRequest(Contract):
    """Provided single-topic assignments, not a fitted topic model.

    covered_periods declares complete calendar months; it does not establish
    corpus completeness. Unknown coverage becomes null, never an implicit zero.
    Rejections block aggregation unless partial-data processing is explicit.
    """

    batch: BatchRequest
    assignments: dict[str, str] = Field(max_length=1000)
    topic_ids: list[str] = Field(min_length=1, max_length=100)
    topic_definition_version: str = Field(min_length=1, max_length=128)
    start: Period
    end: Period
    covered_periods: list[Period] = Field(max_length=240)
    allow_rejected_records: StrictBool = False


class ForecastRequest(Contract):
    series: SeriesRequest
    topic_id: str = Field(min_length=1, max_length=256)
    cutoff: Period
    horizon: int = Field(default=1, ge=1, le=24, strict=True)
    method: Literal["last_value", "seasonal_naive"] = "last_value"
    season_length: int = Field(default=12, ge=1, le=24, strict=True)


class BacktestRequest(Contract):
    series: SeriesRequest
    topic_id: str = Field(min_length=1, max_length=256)
    validation_start: Period
    validation_end: Period
    final_test_start: Period
    horizon: int = Field(default=1, ge=1, le=24, strict=True)
    min_train: int = Field(default=2, ge=1, le=240, strict=True)
    method: Literal["last_value", "seasonal_naive"] = "last_value"
    season_length: int = Field(default=12, ge=1, le=24, strict=True)


class FeaturesRequest(Contract):
    series: SeriesRequest
    topic_id: str = Field(min_length=1, max_length=256)
    lags: list[Lookback] = Field(default_factory=lambda: [1, 2, 3], max_length=24)
    rolling_windows: list[Lookback] = Field(
        default_factory=lambda: [3, 6], max_length=24
    )


class QualityReport(Contract):
    input_rows: int
    accepted_documents: int
    duplicate_rows: int
    rejected_rows: int
    missing_publication_dates: int
    missing_availability_dates: int
    missing_abstracts: int


class Provenance(Contract):
    source: str
    source_id: str
    retrieved_at: str
    access: Literal["unknown", "metadata_only", "open", "authorized"]
    rights_note: str | None


class Document(Contract):
    document_id: str
    doi: str | None
    title: str
    publication_date: str | None
    available_on: str | None
    abstract: str | None
    language: str | None
    keywords: list[str]
    full_text: str | None
    provenance: list[Provenance]


class Rejection(Contract):
    row: int
    code: str
    message: str


class Duplicate(Contract):
    row: int
    document_id: str


class CurationResult(Contract):
    curation_version: str
    data_kind: DataKind
    documents: list[Document]
    dataset_version: str
    input_sha256: str
    quality: QualityReport
    rejections: list[Rejection]
    duplicates: list[Duplicate]


class Exclusion(Contract):
    document_id: str
    reason: str


class SplitResult(Contract):
    dataset_version: str
    train_end: str
    validation_end: str
    test_end: str
    availability_policy: str
    split_version: str
    partition_version: str
    data_kind: DataKind
    partitions: dict[str, list[str]]
    excluded: list[Exclusion]
    fit_policy: str
    availability_assumption: str
    curation_quality: QualityReport


class SeriesPoint(Contract):
    topic_id: str
    period: Period
    count: int | None
    denominator: int | None
    share: float | None
    assignment_coverage: float | None
    coverage: Literal["declared_complete", "unknown"]
    available_documents: int


class SeriesResult(Contract):
    series_version: str
    series_algorithm: str
    dataset_version: str
    topic_definition_version: str
    topic_ids: list[str]
    assignments: dict[str, str]
    start: Period
    end: Period
    covered_periods: list[Period]
    data_kind: DataKind
    unit: Literal["documents"]
    points: list[SeriesPoint]
    missing_date_documents: int
    outside_window_documents: int
    coverage_evidence: str
    assignment_method: str
    curation_quality: QualityReport


class Prediction(Contract):
    period: Period
    value: float


class ReferenceResult(Contract):
    algorithm_version: str
    method: str
    season_length: int | None
    cutoff: Period
    horizon: int
    history_sha256: str
    model_version: str
    unit: str
    predictions: list[Prediction]
    status: Literal["ok", "insufficient_data"]
    reason: str | None


class ForecastResult(ReferenceResult):
    dataset_version: str
    series_version: str
    topic_definition_version: str
    topic_id: str
    data_kind: DataKind
    curation_quality: QualityReport


class Metrics(Contract):
    n: int
    mae: float
    rmse: float
    wape: float | None
    mase_lag1: float | None
    undefined: list[str]


class Fold(Contract):
    cutoff: Period
    forecast: ReferenceResult
    observed: list[float]
    metrics: Metrics


class SkippedFold(Contract):
    cutoff: Period
    reason: str


class BacktestResult(Contract):
    evaluation_version: str
    method: str
    season_length: int
    validation_start: Period
    validation_end: Period
    final_test_start: Period
    horizon: int
    min_train: int
    development_sha256: str
    evaluation_id: str
    status: Literal["ok", "insufficient_data"]
    folds: list[Fold]
    skipped: list[SkippedFold]
    test_policy: str
    dataset_version: str
    series_version: str
    topic_definition_version: str
    topic_id: str
    data_kind: DataKind
    curation_quality: QualityReport


class FeatureRow(Contract):
    target_period: Period
    target_value: float | None
    observed_through: Period | None
    features: dict[str, float | None]
    complete_features: bool


class FeaturesResult(Contract):
    feature_algorithm: str
    lags: list[int]
    rolling_windows: list[int]
    history_sha256: str
    feature_version: str
    rows: list[FeatureRow]
    usage_policy: str
    dataset_version: str
    series_version: str
    topic_definition_version: str
    topic_id: str
    data_kind: DataKind
    curation_quality: QualityReport


class ProblemDetail(Contract):
    code: str
    message: str


class ErrorResponse(Contract):
    detail: ProblemDetail | list[dict[str, Any]]
