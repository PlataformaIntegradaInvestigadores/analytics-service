"""Server-configured local corpus access; protected by the existing local guard."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.analytics import local_processing_only
from app.api.analytics import router as analytics_router
from app.data import documents, quality
from app.schemas.documents import (
    ArticlePage,
    Candidate,
    CorpusQuality,
    DescriptorPage,
    Detail,
    Preparation,
    TopicOutputs,
    WorksetCreation,
    WorksetSummary,
)

router = APIRouter(
    tags=["Local corpus"],
    dependencies=[Depends(local_processing_only)],
    responses=analytics_router.responses,
)


def corpus_path(request: Request):
    path = request.app.state.settings.corpus_database
    if path is None:
        raise HTTPException(
            503,
            detail={
                "code": "corpus_unconfigured",
                "message": "Configure the local corpus snapshot",
            },
        )
    return path


def workset_path(request: Request):
    path = request.app.state.settings.workset_database
    if path is None:
        raise HTTPException(
            503,
            detail={
                "code": "workset_unconfigured",
                "message": "Configure a prepared working set",
            },
        )
    return path


corpus_dependency = Depends(corpus_path)
workset_dependency = Depends(workset_path)


@router.get("/corpus/articles", response_model=ArticlePage)
def articles(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0, le=1000000),
    year: int | None = Query(None, ge=1, le=9999),
    has_abstract: bool | None = None,
    author: str | None = Query(None, min_length=1, max_length=256),
    descriptor: str | None = Query(None, min_length=1, max_length=256),
    path=corpus_dependency,
):
    return documents.article_page(
        path,
        limit=limit,
        offset=offset,
        year=year,
        has_abstract=has_abstract,
        author=author,
        descriptor=descriptor,
    )


@router.get("/corpus/articles/{identifier}", response_model=Detail)
def detail(identifier: str, path=corpus_dependency):
    from app.domain.common import AnalyticsError

    try:
        return documents.article_detail(path, identifier)
    except AnalyticsError as exc:
        if exc.code == "article_not_found":
            raise HTTPException(
                404, detail={"code": exc.code, "message": str(exc)}
            ) from exc
        raise


@router.get("/corpus/descriptors", response_model=DescriptorPage)
def descriptors(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0, le=1000000),
    path=corpus_dependency,
):
    return documents.descriptor_page(path, limit, offset)


@router.get("/corpus/summary", response_model=dict)
def summary(path=corpus_dependency):
    return documents.summary(path)


@router.get("/corpus/quality", response_model=CorpusQuality)
def corpus_quality(path=corpus_dependency):
    return quality.quality_report(path)


@router.post(
    "/corpus/preparation/preview",
    response_model=WorksetSummary,
    response_model_exclude_none=True,
)
def preparation_preview(configuration: Preparation, path=corpus_dependency):
    return quality.preview(path, configuration.model_dump())


@router.post(
    "/corpus/worksets", response_model=WorksetSummary, response_model_exclude_none=True
)
def create_workset(payload: WorksetCreation, request: Request, path=corpus_dependency):
    directory = request.app.state.settings.workset_directory
    if directory is None:
        raise HTTPException(
            503,
            detail={
                "code": "workset_storage_unconfigured",
                "message": "Configure external workset storage",
            },
        )
    return quality.create_workset(
        path, directory, payload.configuration.model_dump(), payload.expected_workset_id
    )


@router.get(
    "/corpus/worksets/{identifier}",
    response_model=WorksetSummary,
    response_model_exclude_none=True,
)
def stored_workset(identifier: str, request: Request):
    from app.domain.common import AnalyticsError

    directory = request.app.state.settings.workset_directory
    if directory is None:
        raise HTTPException(
            503,
            detail={
                "code": "workset_storage_unconfigured",
                "message": "Configure external workset storage",
            },
        )
    try:
        return quality.stored_workset(directory, identifier)
    except AnalyticsError as exc:
        if exc.code == "workset_not_found":
            raise HTTPException(
                404, detail={"code": exc.code, "message": str(exc)}
            ) from exc
        raise


@router.post("/corpus/worksets/preview", response_model=dict)
def preview(configuration: Preparation, path=corpus_dependency):
    return documents.preview(path, configuration.model_dump())


@router.get("/corpus/workset", response_model=dict)
def workset(path=workset_dependency):
    return documents.working_manifest(path)


@router.post("/topics/candidates/protocol", response_model=dict)
def protocol(candidate: Candidate, path=workset_dependency):
    return documents.candidate_protocol(path, candidate.model_dump())


@router.post("/topics/outputs/evaluate", response_model=dict)
def evaluate(payload: TopicOutputs, path=workset_dependency):
    return documents.evaluate_outputs(path, payload.model_dump())
