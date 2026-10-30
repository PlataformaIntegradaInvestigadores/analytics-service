"""Local feasibility slice: immutable Parquet objects + transactional catalog.

This is not a distributed Lakehouse or a replacement for an agreed table format.
"""

import hashlib
import os
import re
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from app.domain.common import AnalyticsError, canonical_json, fingerprint


class VersionedTable:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.catalog = self.root / "catalog.sqlite"
        with closing(sqlite3.connect(self.catalog)) as db, db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS versions "
                "(id TEXT PRIMARY KEY, parent TEXT, file_sha TEXT, metadata TEXT)"
            )
            db.execute("CREATE TABLE IF NOT EXISTS head (id TEXT)")

    def commit(self, rows, *, expected_parent=None):
        import pyarrow as pa
        import pyarrow.parquet as pq

        if not rows or any(not isinstance(row, dict) or not row for row in rows):
            raise AnalyticsError("invalid_table", "Use nonempty object rows")
        columns = set(rows[0])
        if any(set(row) != columns for row in rows):
            raise AnalyticsError(
                "invalid_table", "All rows must declare identical columns"
            )
        table = pa.Table.from_pylist(rows)
        schema = {field.name: str(field.type) for field in table.schema}
        descriptor, temporary = tempfile.mkstemp(dir=self.root, suffix=".parquet")
        os.close(descriptor)
        temporary = Path(temporary)
        try:
            pq.write_table(table, temporary, compression="snappy")
            digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
            metadata = {
                "parent": expected_parent,
                "schema": schema,
                "rows": table.num_rows,
                "file_sha256": digest,
            }
            identifier = fingerprint(metadata)
            with closing(sqlite3.connect(self.catalog)) as db, db:
                db.execute("BEGIN IMMEDIATE")
                head = db.execute("SELECT id FROM head").fetchone()
                if (head[0] if head else None) != expected_parent:
                    raise AnalyticsError(
                        "concurrent_commit", "Head changed; reload before committing"
                    )
                if expected_parent:
                    previous = self.metadata(expected_parent)["schema"]
                    if any(schema.get(key) != value for key, value in previous.items()):
                        raise AnalyticsError(
                            "incompatible_schema",
                            "Only additive schema evolution allowed",
                        )
                destination = self.root / f"{identifier}.parquet"
                if not destination.exists():
                    os.replace(temporary, destination)
                elif hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
                    raise AnalyticsError("table_integrity", "Existing object differs")
                db.execute(
                    "INSERT OR IGNORE INTO versions VALUES (?,?,?,?)",
                    (identifier, expected_parent, digest, canonical_json(metadata)),
                )
                db.execute("DELETE FROM head")
                db.execute("INSERT INTO head VALUES (?)", (identifier,))
            return identifier
        finally:
            temporary.unlink(missing_ok=True)

    def metadata(self, identifier):
        import json

        if not re.fullmatch(r"[a-f0-9]{64}", identifier):
            raise AnalyticsError("invalid_table_id", "Use SHA256 version")
        with closing(sqlite3.connect(self.catalog)) as db:
            row = db.execute(
                "SELECT metadata FROM versions WHERE id=?", (identifier,)
            ).fetchone()
        if row is None:
            raise AnalyticsError("table_not_found", "Unknown committed table")
        metadata = json.loads(row[0])
        if fingerprint(metadata) != identifier:
            raise AnalyticsError("table_integrity", "Metadata digest mismatch")
        return metadata

    def read(self, identifier, columns=None):
        import pyarrow.parquet as pq

        metadata = self.metadata(identifier)
        path = self.root / f"{identifier}.parquet"
        if (
            not path.is_file()
            or hashlib.sha256(path.read_bytes()).hexdigest() != metadata["file_sha256"]
        ):
            raise AnalyticsError("table_integrity", "Missing or changed Parquet object")
        if columns is not None and not set(columns) <= set(metadata["schema"]):
            raise AnalyticsError("invalid_columns", "Unknown projection columns")
        return pq.read_table(path, columns=columns).to_pylist()
