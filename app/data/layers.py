"""Local immutable Parquet/blob objects and atomic multi-table releases.

Extends the existing local Parquet/catalog approach, without claiming a
distributed Lakehouse, Delta/Iceberg compatibility or institutional deployment.
"""

import json
import os
import re
import shutil
import sqlite3
import tempfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from app.core.provenance import sha256_file
from app.domain.common import AnalyticsError, canonical_json, fingerprint


def _identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise AnalyticsError("invalid_release_id", "Use a SHA256 release identifier")


class LayerStore:
    def __init__(self, root, *, create=False):
        self.root = Path(root).resolve()
        self.catalog = self.root / "catalog.sqlite"
        if create:
            self.root.mkdir(parents=True, exist_ok=True)
            (self.root / "objects").mkdir(exist_ok=True)
            with closing(sqlite3.connect(self.catalog)) as db, db:
                db.execute(
                    "CREATE TABLE IF NOT EXISTS releases "
                    "(id TEXT PRIMARY KEY,payload TEXT NOT NULL,published_at TEXT)"
                )
                db.execute("CREATE TABLE IF NOT EXISTS head (id TEXT NOT NULL)")
        elif not self.catalog.is_file():
            raise AnalyticsError(
                "layers_unconfigured", "Existing layer catalog required"
            )

    def _read(self):
        return closing(sqlite3.connect(self.catalog.as_uri() + "?mode=ro", uri=True))

    def _install(self, temporary, extension):
        digest = sha256_file(temporary)
        destination = self.root / "objects" / (digest + extension)
        if destination.exists():
            if sha256_file(destination) != digest:
                raise AnalyticsError("layer_integrity", "Stored object differs")
        else:
            os.replace(temporary, destination)
        return digest

    def _table(self, specification):
        import pyarrow as pa
        import pyarrow.parquet as pq

        schema = specification["schema"]
        descriptor, name = tempfile.mkstemp(dir=self.root, suffix=".parquet.tmp")
        os.close(descriptor)
        temporary = Path(name)
        rows = 0
        try:
            with pq.ParquetWriter(temporary, schema, compression="snappy") as writer:
                for batch in specification["batches"]:
                    if not batch:
                        continue
                    table = pa.Table.from_pylist(batch, schema=schema)
                    writer.write_table(table)
                    rows += len(batch)
            digest = self._install(temporary, ".parquet")
            return {
                "layer": specification["layer"],
                "rows": rows,
                "schema": {f.name: str(f.type) for f in schema},
                "object_sha256": digest,
                "extension": ".parquet",
            }
        finally:
            temporary.unlink(missing_ok=True)

    def _blob(self, source, layer):
        source = Path(source)
        before = sha256_file(source)
        descriptor, name = tempfile.mkstemp(dir=self.root, suffix=".blob.tmp")
        os.close(descriptor)
        temporary = Path(name)
        try:
            with source.open("rb") as incoming, temporary.open("wb") as outgoing:
                shutil.copyfileobj(incoming, outgoing, length=1024 * 1024)
            digest = self._install(temporary, ".blob")
            if digest != before or sha256_file(source) != before:
                raise AnalyticsError(
                    "layer_source_changed", "Source changed during copy"
                )
            return {
                "layer": layer,
                "object_sha256": digest,
                "extension": ".blob",
                "bytes": source.stat().st_size,
            }
        finally:
            temporary.unlink(missing_ok=True)

    def publish(
        self, tables, blobs, lineage, *, expected_parent=None, source_hashes=None
    ):
        if expected_parent is not None:
            _identifier(expected_parent)
        for name, specification in {**tables, **blobs}.items():
            if not re.fullmatch(r"[a-z][a-z0-9_]{1,80}", name) or specification[
                "layer"
            ] not in ("bronze", "silver", "gold", "models"):
                raise AnalyticsError(
                    "invalid_layer_object", "Invalid object name/layer"
                )
        if not tables or set(tables) & set(blobs):
            raise AnalyticsError(
                "invalid_release", "Nonoverlapping named tables required"
            )
        content = {
            "format": "centinela-local-layers-v1",
            "parent": expected_parent,
            "lineage": lineage,
            "tables": {
                name: self._table(spec) for name, spec in sorted(tables.items())
            },
            "blobs": {
                name: self._blob(spec["path"], spec["layer"])
                for name, spec in sorted(blobs.items())
            },
            "storage_scope": (
                "local filesystem Parquet and transactional SQLite catalog"
            ),
            "distributed_lakehouse_verified": False,
        }
        identifier = fingerprint(content)
        if source_hashes and any(
            sha256_file(Path(p)) != digest for p, digest in source_hashes.items()
        ):
            raise AnalyticsError(
                "layer_source_changed", "Inputs changed before publication"
            )
        with closing(sqlite3.connect(self.catalog)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            head = db.execute("SELECT id FROM head").fetchone()
            current = head[0] if head else None
            if current == identifier:
                return self.release(identifier)
            if current != expected_parent:
                raise AnalyticsError(
                    "concurrent_release", "Head changed; reload before publish"
                )
            db.execute(
                "INSERT INTO releases VALUES (?,?,?)",
                (identifier, canonical_json(content), datetime.now(UTC).isoformat()),
            )
            db.execute("DELETE FROM head")
            db.execute("INSERT INTO head VALUES (?)", (identifier,))
        return self.release(identifier)

    def release(self, identifier=None):
        if identifier is not None:
            _identifier(identifier)
        with self._read() as db:
            if identifier is None:
                head = db.execute("SELECT id FROM head").fetchone()
                identifier = head[0] if head else None
            row = db.execute(
                "SELECT payload,published_at FROM releases WHERE id=?", (identifier,)
            ).fetchone()
        if row is None:
            raise AnalyticsError("release_not_found", "No such committed release")
        content = json.loads(row[0])
        if fingerprint(content) != identifier:
            raise AnalyticsError("layer_integrity", "Release manifest differs")
        return {"release_id": identifier, "published_at": row[1], **content}

    def history(self):
        with self._read() as db:
            rows = db.execute(
                "SELECT id,published_at FROM releases ORDER BY published_at,id"
            ).fetchall()
        return [{"release_id": r[0], "published_at": r[1]} for r in rows]

    def object_path(self, release, name, *, table=False):
        spec = release["tables" if table else "blobs"].get(name)
        if spec is None:
            raise AnalyticsError(
                "layer_object_missing", "Release does not contain this object"
            )
        _identifier(spec["object_sha256"])
        expected = ".parquet" if table else ".blob"
        if spec["extension"] != expected:
            raise AnalyticsError("layer_integrity", "Unexpected object type")
        path = self.root / "objects" / (spec["object_sha256"] + expected)
        if not path.is_file() or sha256_file(path) != spec["object_sha256"]:
            raise AnalyticsError("layer_integrity", "Object differs from release")
        return path

    def read_blob(self, release, name):
        return self.object_path(release, name).read_bytes()

    def read_topic_model(self, release, identifier):
        _identifier(identifier)
        model_path = self.object_path(release, "study_topic_models")
        with closing(sqlite3.connect(model_path.as_uri() + "?mode=ro", uri=True)) as db:
            row = db.execute(
                "SELECT payload FROM fitted_models WHERE id=?", (identifier,)
            ).fetchone()
        if row is None:
            raise AnalyticsError("map_model_missing", "Frozen study model is missing")
        return json.loads(row[0])

    def read_table(self, release, name):
        import pyarrow.parquet as pq

        return pq.read_table(self.object_path(release, name, table=True)).to_pylist()

    def verify(self, identifier=None):
        import pyarrow.parquet as pq

        release = self.release(identifier)
        for name, spec in {**release["tables"], **release["blobs"]}.items():
            _identifier(spec["object_sha256"])
            if spec["extension"] not in (".parquet", ".blob"):
                raise AnalyticsError("layer_integrity", "Unexpected object extension")
            path = self.root / "objects" / (spec["object_sha256"] + spec["extension"])
            if not path.is_file() or sha256_file(path) != spec["object_sha256"]:
                raise AnalyticsError(
                    "layer_integrity", "Object failed verification: " + name
                )
            if name in release["tables"]:
                parquet = pq.ParquetFile(path)
                if (
                    parquet.metadata.num_rows != spec["rows"]
                    or {f.name: str(f.type) for f in parquet.schema_arrow}
                    != spec["schema"]
                ):
                    raise AnalyticsError("layer_integrity", "Parquet metadata differs")
        return {
            "status": "passed",
            "release_id": release["release_id"],
            "tables_verified": len(release["tables"]),
            "blobs_verified": len(release["blobs"]),
        }
