"""Local append-only snapshots. API requests never select filesystem paths."""

import sqlite3
from contextlib import closing
from pathlib import Path

from app.domain.common import AnalyticsError, canonical_json, fingerprint
from app.domain.corpus import CURATION_VERSION, curate


class SnapshotStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _connect(self):
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def save(self, records: list[dict], data_kind: str) -> dict:
        result = curate(records, data_kind)
        batch_id = fingerprint(
            {
                "input_sha256": result["input_sha256"],
                "data_kind": data_kind,
                "curation_version": CURATION_VERSION,
            }
        )
        dataset = {
            key: result[key] for key in ("curation_version", "data_kind", "documents")
        }
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS datasets "
                "(version TEXT PRIMARY KEY, payload TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS documents "
                "(dataset_version TEXT REFERENCES datasets(version), "
                "document_id TEXT, payload TEXT NOT NULL, "
                "PRIMARY KEY(dataset_version, document_id))"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS batches "
                "(batch_id TEXT PRIMARY KEY, "
                "dataset_version TEXT REFERENCES datasets(version), "
                "raw_payload TEXT NOT NULL, result_payload TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS batches_by_dataset "
                "ON batches(dataset_version)"
            )
            connection.execute(
                "CREATE VIEW IF NOT EXISTS dataset_inventory AS "
                "SELECT s.version AS dataset_version, "
                "(SELECT COUNT(*) FROM documents d "
                "WHERE d.dataset_version = s.version) "
                "AS document_count, "
                "(SELECT COUNT(*) FROM batches b WHERE b.dataset_version = s.version) "
                "AS batch_count FROM datasets s"
            )
            existing = connection.execute(
                "SELECT result_payload FROM batches WHERE batch_id = ?", (batch_id,)
            ).fetchone()
            if existing and existing[0] != canonical_json(result):
                raise AnalyticsError(
                    "snapshot_corrupt", "Existing batch differs from its identity"
                )
            connection.execute(
                "INSERT OR IGNORE INTO datasets VALUES (?, ?)",
                (result["dataset_version"], canonical_json(dataset)),
            )
            connection.executemany(
                "INSERT OR IGNORE INTO documents VALUES (?, ?, ?)",
                [
                    (result["dataset_version"], d["document_id"], canonical_json(d))
                    for d in result["documents"]
                ],
            )
            connection.execute(
                "INSERT OR IGNORE INTO batches VALUES (?, ?, ?, ?)",
                (
                    batch_id,
                    result["dataset_version"],
                    canonical_json(records),
                    canonical_json(result),
                ),
            )
        return self.load(batch_id)

    def load(self, batch_id: str) -> dict:
        import json

        if not self.path.is_file():
            raise AnalyticsError("snapshot_not_found", "Database does not exist")
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT raw_payload, result_payload, dataset_version "
                "FROM batches WHERE batch_id = ?",
                (batch_id,),
            ).fetchone()
            if row is None:
                raise AnalyticsError("snapshot_not_found", "Unknown batch")
            try:
                records, result = json.loads(row[0]), json.loads(row[1])
                expected = curate(records, result["data_kind"])
            except (json.JSONDecodeError, KeyError, TypeError, AnalyticsError) as exc:
                raise AnalyticsError(
                    "snapshot_corrupt", "Snapshot payload cannot be reconstructed"
                ) from exc
            expected_id = fingerprint(
                {
                    "input_sha256": expected["input_sha256"],
                    "data_kind": result["data_kind"],
                    "curation_version": CURATION_VERSION,
                }
            )
            dataset = connection.execute(
                "SELECT payload FROM datasets WHERE version = ?", (row[2],)
            ).fetchone()
            documents = connection.execute(
                "SELECT payload FROM documents WHERE dataset_version = ? "
                "ORDER BY document_id",
                (row[2],),
            ).fetchall()
            content = {
                key: expected[key]
                for key in ("curation_version", "data_kind", "documents")
            }
            if (
                expected_id != batch_id
                or canonical_json(result) != canonical_json(expected)
                or row[2] != expected["dataset_version"]
                or not dataset
                or dataset[0] != canonical_json(content)
                or [d[0] for d in documents]
                != [canonical_json(d) for d in expected["documents"]]
            ):
                raise AnalyticsError(
                    "snapshot_corrupt", "Snapshot integrity verification failed"
                )
        return {
            "batch_id": batch_id,
            "dataset_version": result["dataset_version"],
            "result": result,
        }
