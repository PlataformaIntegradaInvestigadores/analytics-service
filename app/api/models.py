"""Local registry metadata queries with no training or write endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.analytics import local_processing_only
from app.data import model_queries
from app.domain.common import AnalyticsError
from app.schemas.models import ModelPage, ModelSummary

router = APIRouter(tags=["Local models"], dependencies=[Depends(local_processing_only)])


def query(request, operation, *args):
    path = request.app.state.settings.model_database
    if path is None or not path.is_file():
        raise HTTPException(
            503,
            detail={
                "code": "models_unconfigured",
                "message": "Configure an existing local model registry",
            },
        )
    try:
        return operation(path, *args)
    except AnalyticsError as exc:
        status = {"model_integrity": 409, "model_not_found": 404}.get(exc.code, 422)
        raise HTTPException(
            status, detail={"code": exc.code, "message": str(exc)}
        ) from exc


@router.get("/models", response_model=ModelPage)
def models(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0, le=1000000),
):
    return query(request, model_queries.model_page, limit, offset)


@router.get("/models/{identifier}", response_model=ModelSummary)
def model(request: Request, identifier: str):
    return query(request, model_queries.model_detail, identifier)
