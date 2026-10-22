import copy
import json
import sqlite3

import pytest

from app.data.snapshots import SnapshotStore
from app.domain.common import AnalyticsError, canonical_json, next_month, parse_day
from app.domain.corpus import curate, temporal_split


def test_normalization_preserves_provenance_and_unknowns(record):
    result = curate(
        [
            record(
                title="  Synthetic\n\t document  ",
                doi=" HTTPS://DOI.ORG/10.9999/SYNTHETIC-ONE ",
                language=" ES ",
                keywords=["topic", " topic ", "science"],
                retrieved_at="2026-10-21T07:00:00-05:00",
            )
        ],
        "synthetic",
    )
    document = result["documents"][0]
    assert document["document_id"] == "doi:10.9999/synthetic-one"
    assert document["title"] == "Synthetic document"
    assert document["keywords"] == ["science", "topic"]
    assert document["language"] == "es"
    assert document["abstract"] is None
    assert document["provenance"][0]["retrieved_at"] == "2026-10-21T12:00:00+00:00"
    assert result["quality"]["missing_abstracts"] == 1


@pytest.mark.parametrize(
    "doi", ["doi:10.9999/SYNTHETIC-ONE", "http://dx.doi.org/10.9999/synthetic-one"]
)
def test_doi_aliases(record, doi):
    assert (
        curate([record(doi=doi)], "synthetic")["documents"][0]["doi"]
        == "10.9999/synthetic-one"
    )


def test_deduplication_is_order_independent_and_merges_lineage(record):
    first, second = record(), record(source="other-synthetic-source")
    result = curate([first, second, first], "synthetic")
    reordered = curate([second, first, first], "synthetic")
    assert result["quality"]["accepted_documents"] == 1
    assert result["quality"]["duplicate_rows"] == 2
    assert len(result["documents"][0]["provenance"]) == 2
    assert result["dataset_version"] == reordered["dataset_version"]
    assert result["input_sha256"] != reordered["input_sha256"]
    assert (
        curate([first], "empirical")["dataset_version"]
        != curate([first], "synthetic")["dataset_version"]
    )


def test_content_conflicts_quarantine_every_version_and_reconcile(record):
    result = curate([record(), record(title="Different"), record("two")], "synthetic")
    assert [item["row"] for item in result["rejections"]] == [0, 1]
    quality = result["quality"]
    assert (
        quality["input_rows"]
        == quality["accepted_documents"]
        + quality["rejected_rows"]
        + quality["duplicate_rows"]
    )
    assert quality["accepted_documents"] == 1


def test_source_alias_conflicts_do_not_create_two_documents(record):
    result = curate([record(), record(doi="10.9999/another-synthetic-id")], "synthetic")
    assert result["quality"]["accepted_documents"] == 0
    assert result["quality"]["rejected_rows"] == 2


def test_source_fallback_is_namespaced_and_deterministic(record):
    result = curate(
        [record(doi=None), record(source="different", doi=None)], "synthetic"
    )
    assert len(result["documents"]) == 2
    assert all(d["document_id"].startswith("source:") for d in result["documents"])
    assert result == curate(
        [record(doi=None), record(source="different", doi=None)], "synthetic"
    )


@pytest.mark.parametrize(
    "overrides,code",
    [
        ({"title": None}, "missing_field"),
        ({"source_id": "  "}, "missing_field"),
        ({"title": 9}, "invalid_field"),
        ({"abstract": "x" * 100001}, "invalid_field"),
        ({"publication_date": "2020"}, "invalid_date"),
        ({"publication_date": "2020-02-30"}, "invalid_date"),
        ({"publication_date": "20200115"}, "invalid_date"),
        ({"available_on": "2027-01-01"}, "invalid_availability"),
        ({"doi": "nonsense"}, "invalid_doi"),
        ({"language": "Spanish"}, "invalid_language"),
        ({"keywords": "topic"}, "invalid_keywords"),
        ({"keywords": ["topic", ""]}, "missing_field"),
        ({"keywords": ["x"] * 101}, "invalid_keywords"),
        ({"retrieved_at": "2020-01-01"}, "invalid_retrieval_time"),
        ({"retrieved_at": "not-a-time"}, "invalid_retrieval_time"),
        ({"retrieved_at": "2020-01-01T12:00:00"}, "invalid_retrieval_time"),
        ({"access": "paid"}, "invalid_access"),
        ({"full_text": "Text", "access": "open"}, "unverified_text_access"),
        ({"full_text": "Text", "rights_note": "unknown"}, "unverified_text_access"),
        ({"extra": 1}, "unknown_fields"),
    ],
)
def test_invalid_rows_are_reported_not_silently_dropped(record, overrides, code):
    result = curate([record(**overrides)], "synthetic")
    assert result["quality"]["accepted_documents"] == 0
    assert result["rejections"][0]["code"] == code
    assert "Synthetic document" not in result["rejections"][0]["message"]


@pytest.mark.parametrize("access", ["open", "authorized"])
def test_full_text_requires_explicit_rights_and_access(record, access):
    result = curate(
        [
            record(
                full_text="Synthetic text",
                access=access,
                rights_note="Fixture permission",
            )
        ],
        "synthetic",
    )
    assert result["documents"][0]["full_text"] == "Synthetic text"


def test_unknown_dates_remain_null_and_invalid_record_has_reason(record):
    result = curate([record(publication_date=None, available_on=None), 9], "synthetic")
    assert result["documents"][0]["publication_date"] is None
    assert result["quality"]["missing_publication_dates"] == 1
    assert result["quality"]["missing_availability_dates"] == 1
    assert result["rejections"][0]["code"] == "invalid_record"


@pytest.mark.parametrize(
    "records,kind,code",
    [
        ([], "unknown", "invalid_data_kind"),
        ([{}] * 1001, "synthetic", "batch_limit"),
        (None, "synthetic", "batch_limit"),
        ([{"title": float("nan")}], "synthetic", "invalid_json"),
        ([{"title": object()}], "synthetic", "invalid_json"),
    ],
)
def test_batch_bounds_and_non_json_values(records, kind, code):
    with pytest.raises(AnalyticsError, match=".") as error:
        curate(records, kind)
    assert error.value.code == code


def test_temporal_boundaries_and_availability_exclusions(record):
    records = [
        record("train", publication_date="2020-01-31", available_on="2020-01-31"),
        record("validation", publication_date="2020-02-01", available_on="2020-02-01"),
        record("test", publication_date="2020-03-31", available_on="2020-03-31"),
        record("after", publication_date="2020-04-01", available_on="2020-04-01"),
        record("late", publication_date="2020-01-01", available_on="2020-02-01"),
        record("unknown", publication_date=None),
        record("unverified", available_on=None),
    ]
    dataset = curate(records, "synthetic")
    split = temporal_split(dataset, "2020-01-31", "2020-02-29", "2020-03-31")
    for name in ("train", "validation", "test"):
        assert split["partitions"][name] == [f"doi:10.9999/synthetic-{name}"]
    assert {item["reason"] for item in split["excluded"]} == {
        "missing_publication_date",
        "after_test_window",
        "not_available_at_partition_cutoff",
        "missing_verified_availability",
    }
    assert (
        split["partition_version"]
        == temporal_split(dataset, "2020-01-31", "2020-02-29", "2020-03-31")[
            "partition_version"
        ]
    )
    proxy = temporal_split(
        dataset, "2020-01-31", "2020-02-29", "2020-03-31", "publication_date_proxy"
    )
    assert "doi:10.9999/synthetic-unverified" in proxy["partitions"]["train"]
    assert "not verified" in proxy["availability_assumption"]


@pytest.mark.parametrize(
    "boundaries,policy",
    [
        (("2020-01-31", "2020-01-31", "2020-03-31"), "verified"),
        (("2020-03-31", "2020-02-29", "2020-01-31"), "verified"),
        (("2020-01-31", "2020-02-29", "2020-03-31"), "invented"),
    ],
)
def test_invalid_split_configuration(boundaries, policy):
    with pytest.raises(AnalyticsError):
        temporal_split(curate([], "synthetic"), *boundaries, policy)


def test_calendar_strictness_and_year_transition():
    assert next_month("2020-12") == "2021-01"
    assert parse_day("2020-02-29").day == 29
    for value in ("2020-2-01", None):
        with pytest.raises(AnalyticsError):
            parse_day(value)
    with pytest.raises(AnalyticsError):
        next_month("9999-12")


def test_sqlite_snapshots_are_idempotent_and_reconstruct_exact_batch(tmp_path, record):
    store = SnapshotStore(tmp_path / "snapshots.sqlite")
    records = [
        record(),
        record(),
        record("two"),
        record("bad", publication_date="invalid"),
    ]
    original = copy.deepcopy(records)
    saved = store.save(records, "synthetic")
    assert records == original
    assert store.save(records, "synthetic") == saved
    assert store.load(saved["batch_id"]) == saved
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM batches").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 2
        assert connection.execute(
            "SELECT document_count, batch_count FROM dataset_inventory"
        ).fetchone() == (2, 1)
        assert (
            json.loads(
                connection.execute("SELECT raw_payload FROM batches").fetchone()[0]
            )
            == records
        )
    revised = store.save([record(title="Changed")], "synthetic")
    assert revised["dataset_version"] != saved["dataset_version"]
    assert store.load(saved["batch_id"]) == saved


@pytest.mark.parametrize("table", ["batches", "datasets", "documents"])
def test_snapshot_integrity_rejects_tampering(tmp_path, record, table):
    store = SnapshotStore(tmp_path / "snapshots.sqlite")
    saved = store.save([record()], "synthetic")
    with sqlite3.connect(store.path) as connection:
        column = "result_payload" if table == "batches" else "payload"
        connection.execute(
            f"UPDATE {table} SET {column} = ?",
            (canonical_json({"data_kind": "synthetic"}),),
        )
    with pytest.raises(AnalyticsError, match="integrity"):
        store.load(saved["batch_id"])
    if table == "batches":
        with pytest.raises(AnalyticsError, match="differs"):
            store.save([record()], "synthetic")


def test_snapshot_missing_cases(tmp_path, record):
    store = SnapshotStore(tmp_path / "snapshots.sqlite")
    with pytest.raises(AnalyticsError, match="does not exist"):
        store.load("missing")
    assert not store.path.exists()
    store.save([record()], "synthetic")
    with pytest.raises(AnalyticsError, match="Unknown batch"):
        store.load("missing")
