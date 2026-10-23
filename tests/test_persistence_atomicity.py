import sqlite3

import pytest

from app.data.forecast_runs import ForecastRunStore
from app.data.snapshots import SnapshotStore
from app.domain.common import AnalyticsError, canonical_json, fingerprint


@pytest.mark.parametrize(
    "tamper", ["missing_document", "changed_document", "changed_dataset", "changed_raw"]
)
def test_reingestion_does_not_heal_or_append_to_corrupt_snapshot(
    tmp_path, record, tamper
):
    path = tmp_path / "snapshots.sqlite"
    store = SnapshotStore(path)
    rows = [record(), record("two")]
    batch = store.save(rows, "synthetic")
    with sqlite3.connect(path) as connection:
        if tamper == "missing_document":
            connection.execute(
                "DELETE FROM documents WHERE document_id = ?",
                ("doi:10.9999/synthetic-one",),
            )
        elif tamper == "changed_document":
            connection.execute("UPDATE documents SET payload = '{}' ")
        elif tamper == "changed_dataset":
            connection.execute("UPDATE datasets SET payload = '{}' ")
        else:
            connection.execute("UPDATE batches SET raw_payload = '[]' ")
    before = path.read_bytes()
    candidate = rows if tamper == "changed_raw" else list(reversed(rows))
    with pytest.raises(AnalyticsError) as error:
        store.save(candidate, "synthetic")
    assert error.value.code == "snapshot_corrupt"
    assert path.read_bytes() == before
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM batches").fetchone()[0] == 1
    with pytest.raises(AnalyticsError):
        store.load(batch["batch_id"])


def test_snapshot_insert_trigger_failure_rolls_back_entire_new_batch(tmp_path, record):
    path = tmp_path / "snapshots.sqlite"
    store = SnapshotStore(path)
    original = store.save([record()], "synthetic")
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TRIGGER corrupt_batch AFTER INSERT ON batches BEGIN "
            "UPDATE batches SET raw_payload = '[]' "
            "WHERE batch_id = NEW.batch_id; END"
        )
    with pytest.raises(AnalyticsError, match="during persistence"):
        store.save([record("new")], "synthetic")
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM datasets").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1
    assert store.load(original["batch_id"]) == original


def test_snapshot_restore_opens_existing_database_read_only(tmp_path, record):
    path = tmp_path / "snapshot.sqlite"
    store = SnapshotStore(path)
    saved = store.save([record()], "synthetic")
    before = path.read_bytes()
    assert store.load(saved["batch_id"]) == saved
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("runtime", None),
        ("runtime", {"python": "3.11"}),
        ("code_sha256", {"../../outside": "0" * 64}),
        ("code_sha256", None),
    ],
)
def test_artifact_metadata_and_source_paths_are_validated(
    tmp_path, series_request, field, value
):
    path = tmp_path / "runs.sqlite"
    store = ForecastRunStore(path)
    saved = store.save(
        {"series": series_request, "topic_id": "topic-a", "cutoff": "2020-05"}
    )
    payload = {key: value for key, value in saved.items() if key != "run_id"}
    payload[field] = value
    identifier = fingerprint(payload)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO forecast_runs VALUES (?,?)",
            (identifier, canonical_json(payload)),
        )
    with pytest.raises(AnalyticsError) as error:
        store.load(identifier)
    assert error.value.code == "forecast_run_corrupt"


def test_forecast_trigger_failure_rolls_back_insert(tmp_path, series_request):
    path = tmp_path / "runs.sqlite"
    store = ForecastRunStore(path)
    request = {"series": series_request, "topic_id": "topic-a", "cutoff": "2020-05"}
    original = store.save(request)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TRIGGER corrupt_run AFTER INSERT ON forecast_runs BEGIN "
            "UPDATE forecast_runs SET payload = '{}' "
            "WHERE run_id = NEW.run_id; END"
        )
    with pytest.raises(AnalyticsError, match="during persistence"):
        store.save({**request, "horizon": 2})
    assert store.load(original["run_id"]) == original
    with sqlite3.connect(path) as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM forecast_runs").fetchone()[0] == 1
        )
