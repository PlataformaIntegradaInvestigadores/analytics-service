"""Local development endpoints; remote access awaits Centinela identity integration."""

from fastapi import APIRouter, Depends, HTTPException, Request

from app.application import analysis
from app.schemas.analytics import (
    BacktestRequest,
    BacktestResult,
    BatchRequest,
    CurationResult,
    ErrorResponse,
    FeaturesRequest,
    FeaturesResult,
    ForecastRequest,
    ForecastResult,
    SeriesRequest,
    SeriesResult,
    SplitRequest,
    SplitResult,
)


def local_processing_only(request: Request) -> None:
    if request.app.state.settings.environment != "local":
        raise HTTPException(
            status_code=503,
            detail={
                "code": "integration_pending",
                "message": "Remote identity integration is pending",
            },
        )


router = APIRouter(
    tags=["Local analytics"],
    dependencies=[Depends(local_processing_only)],
    responses={
        422: {
            "model": ErrorResponse,
            "description": "Invalid contract or analytical input",
        },
        503: {
            "model": ErrorResponse,
            "description": "Remote identity integration pending",
        },
    },
)


@router.post("/datasets/curate", response_model=CurationResult)
def curate(request: BatchRequest):
    return analysis.curate_batch(request.model_dump())


@router.post("/datasets/split", response_model=SplitResult)
def split(request: SplitRequest):
    return analysis.split_batch(request.model_dump())


@router.post("/series/build", response_model=SeriesResult)
def series(request: SeriesRequest):
    return analysis.aggregate_batch(request.model_dump())


@router.post("/forecasts/reference", response_model=ForecastResult)
def forecast(request: ForecastRequest):
    return analysis.forecast_batch(request.model_dump())


@router.post("/evaluations/backtest", response_model=BacktestResult)
def backtest(request: BacktestRequest):
    return analysis.backtest_batch(request.model_dump())


@router.post("/forecasts/features", response_model=FeaturesResult)
def features(request: FeaturesRequest):
    return analysis.features_batch(request.model_dump())
