"""Public metadata only: no vocabulary, texts, coefficients or local paths."""

from typing import Literal

from pydantic import Field

from app.schemas.analytics import Contract


class ModelSummary(Contract):
    model_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    workset_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    method: Literal["tfidf-nmf"]
    purpose: Literal["technical"]
    evaluation_status: Literal["not_research_validated"] = "not_research_validated"
    fit_document_count: int = Field(ge=2, le=100000)
    configuration: dict[str, int | float]
    versions: dict[str, str]
    cutoff: str | None
    temporal_status: Literal[
        "verified_declared_availability", "not_temporal_validation"
    ]


class ModelPage(Contract):
    status: Literal["ok", "empty"]
    total: int
    limit: int
    offset: int
    items: list[ModelSummary]
