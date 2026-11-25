"""Read-only aggregate study results, guarded by local integration policy."""

import json

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.access import analytics_read_access
from app.api.layers import _release
from app.data.documents import read_database
from app.data.layers import LayerStore
from app.domain.common import AnalyticsError, fingerprint
from app.domain.forecast_evidence import forecast_comparison

router = APIRouter(
    tags=["Research study"], dependencies=[Depends(analytics_read_access)]
)
_HISTORICAL_PDF_LIMITATION = (
    "Title and abstract only; full PDF portion of signed plan remains pending"
)


def read_study(path):
    with read_database(path) as db:
        row = db.execute(
            "SELECT payload FROM study ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if row is None:
        raise AnalyticsError("study_missing", "No completed study in store")
    return clean_study(json.loads(row[0]))


def clean_study(result):
    stored = result.pop("report_sha256", None)
    if stored != fingerprint(result):
        raise AnalyticsError("study_integrity", "Stored study fingerprint mismatch")
    # Omit vocabularies, fit IDs, paths and approval text from the aggregate view.
    result.pop("identity", None)
    result["protocol"].pop("approval_reference", None)
    result["preparation"].pop("source_year_counts", None)
    for topic in result["topics"]:
        topic.pop("representative_article_ids", None)
    if "limitations" in result:
        result["limitations"] = [
            "Text modeling uses titles and abstracts."
            if note == _HISTORICAL_PDF_LIMITATION
            else note
            for note in result["limitations"]
        ]
    return result


@router.get("/study", response_model=dict)
def study(request: Request, release_id: str | None = None):
    root = request.app.state.settings.lake_directory
    if root is not None:
        archive = LayerStore(root)
        release = _release(request, release_id)
        data = clean_study(json.loads(archive.read_blob(release, "study_results")))
        if data["run_id"] != release["lineage"]["study_run_id"]:
            raise AnalyticsError(
                "layer_study_mismatch", "Study/release identities differ"
            )
        series = {}
        for row in archive.read_table(release, "gold_annual_series"):
            topic = row.pop("topic_id")
            series.setdefault(topic, []).append(row)
        if series != data["series"]:
            raise AnalyticsError(
                "layer_study_mismatch", "Parquet series differ from fitted study"
            )
        data["series"] = series
        data["storage_lineage"] = {
            "release_id": release["release_id"],
            "storage_scope": release["storage_scope"],
        }
    else:
        path = request.app.state.settings.study_database
        if path is None or release_id is not None:
            raise HTTPException(
                503,
                detail={
                    "code": "study_unconfigured",
                    "message": "Configure a completed study with the requested storage",
                },
            )
        data = read_study(path)
    if "validation_records" in data.get("prediction", {}):
        data["forecast_comparison"] = forecast_comparison(
            data["series"], data["protocol"], data["prediction"]
        )
    return data


@router.get("/study/review", response_model=dict)
def review(request: Request):
    root = request.app.state.settings.lake_directory
    if root is not None:
        archive = LayerStore(root)
        release = archive.release()
        data = json.loads(archive.read_blob(release, "review_results"))
        expected = data.pop("report_sha256", None)
        if (
            fingerprint(data) != expected
            or data["run_id"] != release["lineage"]["review_run_id"]
        ):
            raise AnalyticsError(
                "layer_review_mismatch", "Review/release identities differ"
            )
        data.pop("identity", None)
        return data
    path = request.app.state.settings.review_database
    if path is None:
        raise HTTPException(
            503,
            detail={
                "code": "review_unconfigured",
                "message": "Configure completed research review",
            },
        )
    with read_database(path) as db:
        row = db.execute(
            "SELECT payload FROM review ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if row is None:
        raise AnalyticsError("review_missing", "No completed review")
    data = json.loads(row[0])
    expected = data.pop("report_sha256", None)
    if fingerprint(data) != expected:
        raise AnalyticsError("review_integrity", "Review content changed")
    data.pop("identity", None)
    return data
