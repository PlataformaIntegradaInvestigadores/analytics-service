"""Local workflow contracts; database location is server configuration only."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import ValidationError

from app.api.analytics import local_processing_only
from app.api.analytics import router as analytics_router
from app.application import analysis
from app.application.presentation import (
    dashboard_contract,
    explanation_state,
)
from app.data.experiments import ExperimentStore
from app.data.exports import field_dictionary
from app.domain.common import AnalyticsError
from app.schemas.analytics import DataKind, ErrorResponse, SeriesResult
from app.schemas.workflow import (
    CatalogRequest,
    CatalogResult,
    CatalogSeriesRequest,
    ComparisonRequest,
    ComparisonResult,
    DashboardContract,
    DashboardView,
    ExperimentArtifact,
    ExperimentKind,
    ExperimentPage,
    ExperimentRequest,
    ExplanationState,
    ExportDictionary,
)

router = APIRouter(
    tags=["Local workflow"],
    dependencies=[Depends(local_processing_only)],
    responses={
        **analytics_router.responses,
        404: {"model": ErrorResponse, "description": "Unknown saved experiment"},
    },
)


def store(request: Request) -> ExperimentStore:
    path = request.app.state.settings.artifact_database
    if path is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "artifact_store_unconfigured",
                "message": "Configure the local artifact database",
            },
        )
    return ExperimentStore(path)


def saved(identifier: str, database: ExperimentStore) -> dict:
    try:
        return database.load(identifier)
    except AnalyticsError as exc:
        if exc.code == "experiment_not_found":
            raise HTTPException(
                status_code=404, detail={"code": exc.code, "message": str(exc)}
            ) from exc
        raise


store_dependency = Depends(store)


@router.get("/datasets/dictionary", response_model=ExportDictionary)
def dictionary():
    return field_dictionary()


@router.post("/topics/catalog", response_model=CatalogResult)
def catalog(request: CatalogRequest):
    return analysis.catalog_batch(request.model_dump(mode="json"))


@router.post("/series/from-catalog", response_model=SeriesResult)
def catalog_series(request: CatalogSeriesRequest):
    return analysis.catalog_series_batch(request.model_dump(mode="json"))


@router.post("/evaluations/compare", response_model=ComparisonResult)
def compare(request: ComparisonRequest):
    return analysis.comparison_batch(request.model_dump(mode="json"))


@router.post("/experiments", response_model=ExperimentArtifact)
def save_experiment(
    request: ExperimentRequest, database: ExperimentStore = store_dependency
):
    try:
        return database.save(request.model_dump(mode="json"))
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_experiment_request",
                "message": "Request does not match the selected experiment kind",
            },
        ) from exc


@router.get("/experiments", response_model=ExperimentPage)
def experiments(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=1000000),
    kind: ExperimentKind | None = None,
    data_kind: DataKind | None = None,
    topic_id: str | None = Query(default=None, min_length=1, max_length=256),
    status: Literal["ok", "insufficient_data", "declared"] | None = None,
    database: ExperimentStore = store_dependency,
):
    return database.query(
        limit=limit,
        offset=offset,
        kind=kind,
        data_kind=data_kind,
        topic_id=topic_id,
        status=status,
    )


@router.get("/experiments/{identifier}", response_model=ExperimentArtifact)
def experiment(identifier: str, database: ExperimentStore = store_dependency):
    return saved(identifier, database)


@router.get("/experiments/{identifier}/explanation", response_model=ExplanationState)
def explanation(
    identifier: str,
    scope: Literal["local", "global"] = "local",
    database: ExperimentStore = store_dependency,
):
    return explanation_state(saved(identifier, database), scope)


@router.get("/experiments/{identifier}/dashboard", response_model=DashboardView)
def dashboard(
    identifier: str,
    start: str | None = None,
    end: str | None = None,
    database: ExperimentStore = store_dependency,
):
    # Map an absent identifier to the same explicit 404 as detail/explanation.
    saved(identifier, database)
    return database.dashboard(identifier, start, end)


@router.get("/dashboard/contract", response_model=DashboardContract)
def presentation_contract():
    return dashboard_contract()
