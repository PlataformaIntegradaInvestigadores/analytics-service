"""Deterministic curation; no remote fetching, fitting, or invented dates."""

import re
import unicodedata
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any
from urllib.parse import unquote

from app.domain.common import AnalyticsError, fingerprint, parse_day

CURATION_VERSION = "curation-v1"
FIELDS = {
    "source",
    "source_id",
    "doi",
    "title",
    "publication_date",
    "abstract",
    "language",
    "keywords",
    "full_text",
    "access",
    "rights_note",
    "retrieved_at",
    "available_on",
}


def _text(value: Any, field: str, *, required: bool = False) -> str | None:
    if value is None:
        if required:
            raise AnalyticsError("missing_field", f"{field} is required")
        return None
    if not isinstance(value, str) or len(value) > 100_000:
        raise AnalyticsError("invalid_field", f"{field} must be bounded text")
    result = " ".join(unicodedata.normalize("NFKC", value).split())
    if required and not result:
        raise AnalyticsError("missing_field", f"{field} is required")
    return result or None


def _doi(value: Any) -> str | None:
    result = _text(value, "doi")
    if result is None:
        return None
    result = unquote(result).lower()
    result = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", result)
    if not re.fullmatch(r"10\.\d{4,9}/\S+", result):
        raise AnalyticsError("invalid_doi", "DOI syntax is invalid")
    return result


def _normalize(raw: dict) -> dict:
    if set(raw) - FIELDS:
        raise AnalyticsError("unknown_fields", "Record contains unsupported fields")
    source = _text(raw.get("source"), "source", required=True)
    source_id = _text(raw.get("source_id"), "source_id", required=True)
    title = _text(raw.get("title"), "title", required=True)
    doi = _doi(raw.get("doi"))
    publication_date = _text(raw.get("publication_date"), "publication_date")
    available_on = _text(raw.get("available_on"), "available_on")
    for value in (publication_date, available_on):
        if value is not None:
            parse_day(value)
    retrieved = _text(raw.get("retrieved_at"), "retrieved_at", required=True)
    try:
        instant = datetime.fromisoformat(retrieved.replace("Z", "+00:00"))
        if instant.tzinfo is None or "T" not in retrieved:
            raise ValueError
        instant = instant.astimezone(UTC)
    except ValueError as exc:
        raise AnalyticsError(
            "invalid_retrieval_time",
            "retrieved_at requires a timezone-aware ISO instant",
        ) from exc
    if available_on and parse_day(available_on) > instant.date():
        raise AnalyticsError(
            "invalid_availability", "Availability cannot be later than retrieval"
        )
    access = raw.get("access", "unknown")
    if access not in ("unknown", "metadata_only", "open", "authorized"):
        raise AnalyticsError("invalid_access", "Unsupported access classification")
    full_text = _text(raw.get("full_text"), "full_text")
    rights = _text(raw.get("rights_note"), "rights_note")
    if full_text and (access not in ("open", "authorized") or not rights):
        raise AnalyticsError(
            "unverified_text_access", "Full text requires access and rights evidence"
        )
    language = _text(raw.get("language"), "language")
    if language:
        language = language.lower()
        if not re.fullmatch(r"[a-z]{2,3}", language):
            raise AnalyticsError(
                "invalid_language", "Use a two/three-letter language code"
            )
    keywords = raw.get("keywords", [])
    if not isinstance(keywords, list) or len(keywords) > 100:
        raise AnalyticsError("invalid_keywords", "keywords must be a bounded list")
    keywords = sorted(
        {text for item in keywords if (text := _text(item, "keyword", required=True))}
    )
    return {
        "document_id": (
            "doi:" + doi if doi else "source:" + fingerprint([source, source_id])
        ),
        "doi": doi,
        "title": title,
        "publication_date": publication_date,
        "available_on": available_on,
        "abstract": _text(raw.get("abstract"), "abstract"),
        "language": language,
        "keywords": keywords,
        "full_text": full_text,
        "provenance": [
            {
                "source": source,
                "source_id": source_id,
                "retrieved_at": instant.isoformat(),
                "access": access,
                "rights_note": rights,
            }
        ],
    }


def curate(records: list[dict], data_kind: str) -> dict:
    if data_kind not in ("synthetic", "empirical"):
        raise AnalyticsError("invalid_data_kind", "Declare synthetic or empirical data")
    if not isinstance(records, list) or len(records) > 1000:
        raise AnalyticsError("batch_limit", "A batch supports at most 1000 records")
    try:
        input_sha256 = fingerprint(records)
    except (TypeError, ValueError) as exc:
        raise AnalyticsError(
            "invalid_json", "Records must contain finite JSON values"
        ) from exc
    groups: dict[str, list[tuple[int, dict]]] = defaultdict(list)
    rejected = []
    for index, raw in enumerate(records):
        try:
            if not isinstance(raw, dict):
                raise AnalyticsError("invalid_record", "Each record must be an object")
            document = _normalize(raw)
            groups[document["document_id"]].append((index, document))
        except AnalyticsError as exc:
            rejected.append({"row": index, "code": exc.code, "message": str(exc)})
    aliases: dict[tuple[str, str], set[str]] = defaultdict(set)
    for document_id, group in groups.items():
        for _, document in group:
            reference = document["provenance"][0]
            aliases[reference["source"], reference["source_id"]].add(document_id)
    conflicting_ids = {
        document_id
        for identifiers in aliases.values()
        if len(identifiers) > 1
        for document_id in identifiers
    }
    documents, duplicates = [], []
    for document_id, group in sorted(groups.items()):
        signatures = {
            fingerprint({k: v for k, v in item.items() if k != "provenance"})
            for _, item in group
        }
        if len(signatures) > 1 or document_id in conflicting_ids:
            rejected.extend(
                {
                    "row": index,
                    "code": "identifier_conflict",
                    "message": "Conflicting content for the same identifier",
                }
                for index, _ in group
            )
            continue
        document = group[0][1].copy()
        references = {
            fingerprint(ref): ref for _, item in group for ref in item["provenance"]
        }
        document["provenance"] = [references[key] for key in sorted(references)]
        documents.append(document)
        duplicates.extend(
            {"row": index, "document_id": document_id} for index, _ in group[1:]
        )
    quality = {
        "input_rows": len(records),
        "accepted_documents": len(documents),
        "duplicate_rows": len(duplicates),
        "rejected_rows": len(rejected),
        "missing_publication_dates": sum(
            d["publication_date"] is None for d in documents
        ),
        "missing_availability_dates": sum(d["available_on"] is None for d in documents),
        "missing_abstracts": sum(d["abstract"] is None for d in documents),
    }
    dataset = {
        "curation_version": CURATION_VERSION,
        "data_kind": data_kind,
        "documents": documents,
    }
    return {
        **dataset,
        "dataset_version": fingerprint(dataset),
        "input_sha256": input_sha256,
        "quality": quality,
        "rejections": sorted(rejected, key=lambda x: x["row"]),
        "duplicates": sorted(duplicates, key=lambda x: x["row"]),
    }


def temporal_split(
    dataset: dict,
    train_end: str,
    validation_end: str,
    test_end: str,
    availability_policy: str = "verified",
) -> dict:
    boundaries = [parse_day(value) for value in (train_end, validation_end, test_end)]
    if not boundaries[0] < boundaries[1] < boundaries[2]:
        raise AnalyticsError("invalid_cutoffs", "Require train < validation < test end")
    if availability_policy not in ("verified", "publication_date_proxy"):
        raise AnalyticsError("invalid_policy", "Unknown availability policy")
    partitions: dict[str, list[str]] = {"train": [], "validation": [], "test": []}
    excluded = []
    for document in dataset["documents"]:
        publication = document["publication_date"]
        reason = None
        if publication is None:
            reason = "missing_publication_date"
        elif publication > test_end:
            reason = "after_test_window"
        else:
            index = (
                0
                if publication <= train_end
                else 1 if publication <= validation_end else 2
            )
            availability = document["available_on"]
            if availability_policy == "publication_date_proxy":
                availability = availability or publication
            if availability is None:
                reason = "missing_verified_availability"
            elif parse_day(availability) > boundaries[index]:
                reason = "not_available_at_partition_cutoff"
            else:
                partitions[list(partitions)[index]].append(document["document_id"])
        if reason:
            excluded.append({"document_id": document["document_id"], "reason": reason})
    configuration = {
        "dataset_version": dataset["dataset_version"],
        "train_end": train_end,
        "validation_end": validation_end,
        "test_end": test_end,
        "availability_policy": availability_policy,
        "split_version": "temporal-v1",
    }
    return {
        **configuration,
        "partition_version": fingerprint(configuration),
        "data_kind": dataset["data_kind"],
        "partitions": partitions,
        "excluded": excluded,
        "fit_policy": "Fit learned transformations on training only; not executed here",
        "availability_assumption": (
            "Publication date may proxy unknown availability; "
            "not verified operational history"
            if availability_policy == "publication_date_proxy"
            else "Explicit availability required"
        ),
    }
