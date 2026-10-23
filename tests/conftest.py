"""All generated records are synthetic; no Centinela corpus is represented."""

import pytest


@pytest.fixture
def record():
    def make(identifier="one", **overrides):
        return {
            "source": "synthetic-fixture",
            "source_id": identifier,
            "doi": f"10.9999/synthetic-{identifier}",
            "title": "Synthetic document",
            "publication_date": "2020-01-15",
            "available_on": "2020-01-15",
            "retrieved_at": "2026-10-21T12:00:00Z",
            **overrides,
        }

    return make


@pytest.fixture
def batch(record):
    return {"data_kind": "synthetic", "records": [record()]}


@pytest.fixture
def series_request(record):
    records = []
    assignments = {}
    for month in range(1, 7):
        for index in range(month):
            identifier = f"{month}-{index}"
            records.append(
                record(
                    identifier,
                    publication_date=f"2020-{month:02d}-15",
                    available_on=f"2020-{month:02d}-15",
                )
            )
            assignments[f"doi:10.9999/synthetic-{identifier}"] = "topic-a"
    return {
        "batch": {"data_kind": "synthetic", "records": records},
        "assignments": assignments,
        "topic_ids": ["topic-a", "topic-b"],
        "topic_definition_version": "synthetic-fixed-topics-v1",
        "start": "2020-01",
        "end": "2020-06",
        "covered_periods": [f"2020-{month:02d}" for month in range(1, 7)],
    }
