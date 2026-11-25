"""Protected release metadata; never expose raw data, blobs or filesystem paths."""

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.access import analytics_read_access
from app.data.layers import LayerStore
from app.domain.common import AnalyticsError

router = APIRouter(tags=["Data lineage"], dependencies=[Depends(analytics_read_access)])


def _store(request):
    root = request.app.state.settings.lake_directory
    if root is None:
        raise HTTPException(
            503,
            detail={
                "code": "layers_unconfigured",
                "message": "Configure a published layer catalog",
            },
        )
    return LayerStore(root)


def _release(request, identifier=None):
    try:
        return _store(request).release(identifier)
    except AnalyticsError as exc:
        raise HTTPException(
            {
                "release_not_found": 404,
                "layers_unconfigured": 503,
                "invalid_release_id": 422,
            }.get(exc.code, 409),
            detail={"code": exc.code, "message": str(exc)},
        ) from exc


@router.get("/lineage/releases", response_model=dict)
def releases(request: Request):
    return {"items": _store(request).history()}


@router.get("/lineage/current", response_model=dict)
def current(request: Request):
    return _release(request)


@router.get("/lineage/releases/{identifier}", response_model=dict)
def release(request: Request, identifier: str):
    return _release(request, identifier)
