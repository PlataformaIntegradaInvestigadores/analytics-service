"""Verify map/API consistency against actual committed research artifacts."""

import argparse
import importlib.util
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.provenance import sha256_file, source_files
from app.data.layers import LayerStore
from app.domain.common import fingerprint
from app.main import create_app


def audit(root):
    archive = LayerStore(root)
    release = archive.release()
    before = sha256_file(archive.catalog)
    with TestClient(create_app(Settings(lake_directory=root))) as client:
        response = client.get("/api/v1/topic-map")
        response.raise_for_status()
        full = response.json()
        assert (
            sum(n["count"] for n in full["nodes"]) + full["unassigned"]
            == full["denominator"]
        )
        filtered = client.get(
            "/api/v1/topic-map",
            params={
                "start_year": 2016,
                "end_year": 2018,
                "release_id": release["release_id"],
            },
        ).json()
        assert filtered["model_id"] == full["model_id"]
        assert filtered["edges"] == full["edges"]
        series = archive.read_table(release, "gold_annual_series")
        for node in filtered["nodes"]:
            assert node["count"] == sum(
                p["count"]
                for p in series
                if p["topic_id"] == node["topic_id"] and 2016 <= p["year"] <= 2018
            )
        page_counts = {}
        for node in full["nodes"]:
            params = {
                "topic_id": node["topic_id"],
                "release_id": full["release_id"],
                "limit": 20,
            }
            page = client.get("/api/v1/topic-map/documents", params=params)
            page.raise_for_status()
            data = page.json()
            assert data["total"] == node["count"]
            assert len({d["article_id"] for d in data["items"]}) == len(data["items"])
            assert all(d["title"] for d in data["items"])
            assert all(set(d) == {"article_id", "year", "title"} for d in data["items"])
            page_counts[node["topic_id"]] = data["total"]
        empty = client.get("/api/v1/topic-map?start_year=2090&end_year=2100").json()
        assert empty["denominator"] == 0
        assert (
            client.get("/api/v1/topic-map?start_year=2020&end_year=2000").status_code
            == 422
        )
        assert client.get("/api/v1/topic-map?release_id=invalid").status_code == 422
        assert client.get("/api/v1/study").status_code == 200
    assert archive.release()["release_id"] == release["release_id"]
    assert sha256_file(archive.catalog) == before
    return {
        "status": "passed",
        "data": "existing real research snapshot",
        "release_id": full["release_id"],
        "model_id": full["model_id"],
        "documents": full["denominator"],
        "unassigned": full["unassigned"],
        "nodes": len(full["nodes"]),
        "edges_at_0_2": len(full["edges"]),
        "document_totals": page_counts,
        "filters_preserve_model_and_edges": True,
        "series_reconciled": True,
        "release_unchanged": True,
        "bertopic_installed": importlib.util.find_spec("bertopic") is not None,
        "new_scientific_evaluation": False,
        "human_sessions_performed": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.store)
    result["software_sha256"] = fingerprint(source_files())
    with args.output.open("x", encoding="utf8") as stream:
        json.dump(result, stream, indent=2)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
