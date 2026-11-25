"""Authorized, read-only thematic exploration of committed layer releases."""

import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.access import analytics_read_access
from app.api.layers import _release, _store
from app.application.topic_map import frozen_map

router = APIRouter(tags=["Topic map"], dependencies=[Depends(analytics_read_access)])


@router.get("/topic-map")
def topic_map(
    request: Request,
    release_id: str | None = None,
    start_year: int | None = Query(None, ge=1900, le=2100),
    end_year: int | None = Query(None, ge=1900, le=2100),
    threshold: float = Query(0.2, ge=0, le=1),
):
    archive = _store(request)
    release = _release(request, release_id)
    result, _ = frozen_map(archive, release, start_year, end_year, threshold)
    return result


@router.get("/topic-map/documents")
def topic_documents(
    request: Request,
    topic_id: str,
    release_id: str,
    start_year: int | None = Query(None, ge=1900, le=2100),
    end_year: int | None = Query(None, ge=1900, le=2100),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=50),
):
    archive = _store(request)
    release = _release(request, release_id)
    result, selected = frozen_map(archive, release, start_year, end_year)
    if topic_id not in {n["topic_id"] for n in result["nodes"]}:
        raise HTTPException(404, detail={"code": "topic_not_found"})
    selected = sorted(
        (d for d in selected if d["topic_id"] == topic_id),
        key=lambda d: (d["year"], d["article_id"]),
    )
    page = selected[offset : offset + limit]
    wanted = {d["article_id"] for d in page}
    titles = {}
    for row in archive.read_table(release, "silver_articles"):
        if row["article_id"] in wanted:
            titles[row["article_id"]] = json.loads(row["document"])["title"]
    return {
        "release_id": release["release_id"],
        "model_id": result["model_id"],
        "topic_id": topic_id,
        "total": len(selected),
        "offset": offset,
        "limit": limit,
        "items": [
            {
                "article_id": d["article_id"],
                "year": d["year"],
                "title": titles[d["article_id"]],
            }
            for d in page
        ],
    }
