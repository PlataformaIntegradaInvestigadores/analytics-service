"""Aggregate diagnostics and server-managed, immutable development worksets."""

import json
import os
import tempfile
from collections import Counter
from pathlib import Path

from app.core.provenance import source_files
from app.data import documents
from app.domain.common import AnalyticsError, fingerprint
from app.domain.text import prepare_text


def quality_report(path):
    lengths = Counter({"0": 0, "1_49": 0, "50_199": 0, "200_plus": 0})
    duplicates, years = Counter(), Counter()
    total = absent = day_one = january_one = unknown_language = 0
    with documents.read_database(path) as connection:
        origin = documents.manifest(connection)
        for publication, encoded in connection.execute(
            "SELECT publication_date,document FROM articles ORDER BY article_id"
        ):
            doc = json.loads(encoded)
            prepared = prepare_text(doc["title"], doc["abstract"])
            size = len(prepare_text("", doc["abstract"])["tokens"])
            bucket = (
                "0"
                if size == 0
                else "1_49" if size < 50 else "50_199" if size < 200 else "200_plus"
            )
            lengths[bucket] += 1
            total += 1
            absent += not prepared["has_abstract"]
            unknown_language += not doc.get("language")
            duplicates[prepared["duplicate_key"]] += 1
            years[publication[:4]] += 1
            day_one += publication[8:10] == "01"
            january_one += publication[5:10] == "01-01"
    content = {
        "quality_version": "aggregate-document-quality-v1",
        "source_version": origin["source_version"],
        "source_sha256": origin["source_sha256"],
        "software_sha256": source_files(),
        "articles": total,
        "missing_abstracts": absent,
        "abstract_token_buckets": dict(lengths),
        "duplicate_text_groups": sum(n > 1 for n in duplicates.values()),
        "duplicate_text_excess": sum(n - 1 for n in duplicates.values()),
        "language": {
            "unknown": unknown_language,
            "declared": total - unknown_language,
            "detection": "not_executed",
        },
        "dates": {
            "day_one": day_one,
            "january_one": january_one,
            "articles_by_year": dict(sorted(years.items())),
            "precision": "unverified",
            "coverage": "unverified_snapshot",
        },
        "policy": (
            "Development snapshot; duplicate text is not proof of duplicate "
            "publications. Date concentrations do not establish precision or "
            "indexation lag. No language has been inferred."
        ),
    }
    return {"quality_id": fingerprint(content), **content}


def compact_manifest(manifest):
    return {
        key: manifest[key]
        for key in (
            "workset_id",
            "preparation_version",
            "configuration",
            "source_version",
            "source_sha256",
            "software_sha256",
            "counts",
            "purpose",
            "training",
            "language",
            "temporal_precision",
        )
    } | {"duplicate_groups": len(manifest["duplicate_groups"])}


def preview(path, configuration):
    return compact_manifest(documents.preview(path, configuration))


def storage_directory(directory):
    if directory is None:
        raise AnalyticsError(
            "workset_storage_unconfigured",
            "Configure external workset storage on the server",
        )
    directory = Path(directory).resolve()
    repository = Path(__file__).resolve().parents[2]
    if directory.is_relative_to(repository):
        raise AnalyticsError(
            "unsafe_workset_directory", "Keep worksets outside the repository"
        )
    return directory


def stored_workset(directory, identifier):
    if len(identifier) != 64 or any(c not in "0123456789abcdef" for c in identifier):
        raise AnalyticsError("invalid_workset_id", "Use a SHA-256 workset identifier")
    directory = storage_directory(directory)
    path = (directory / (identifier + ".sqlite")).resolve()
    if not path.is_relative_to(directory):
        raise AnalyticsError(
            "unsafe_workset_path", "Working set leaves configured storage"
        )
    if not path.is_file():
        raise AnalyticsError("workset_not_found", "Working set does not exist")
    result = documents.working_manifest(path)
    if result["workset_id"] != identifier:
        raise AnalyticsError(
            "workset_corrupt", "Working-set filename does not match identity"
        )
    return compact_manifest(result)


def create_workset(source, directory, configuration, expected_workset_id=None):
    directory = storage_directory(directory)
    directory.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=".preparation-", suffix=".sqlite", dir=directory
    )
    os.close(descriptor)
    temporary = Path(name)
    temporary.unlink()
    try:
        result = documents.save_workset(source, temporary, configuration)
        if (
            expected_workset_id is not None
            and result["workset_id"] != expected_workset_id
        ):
            raise AnalyticsError(
                "preparation_changed",
                "Preview no longer matches the current preparation",
            )
        destination = directory / (result["workset_id"] + ".sqlite")
        if not destination.resolve().is_relative_to(directory):
            raise AnalyticsError(
                "unsafe_workset_path", "Working set leaves configured storage"
            )
        try:
            os.link(temporary, destination)
            reused = False
        except FileExistsError:
            stored_workset(directory, result["workset_id"])
            reused = True
        return {**compact_manifest(result), "reused": reused}
    finally:
        temporary.unlink(missing_ok=True)
