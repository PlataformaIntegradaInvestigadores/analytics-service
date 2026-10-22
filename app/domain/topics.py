"""Versioned caller-supplied thematic evidence, without fitting a topic model."""

from app.domain.common import AnalyticsError, fingerprint, parse_day


def build_catalog(
    dataset: dict,
    topics: list[dict],
    assignments: dict[str, str],
    method: str,
    model_version: str | None = None,
    fit_document_ids: list[str] | None = None,
    fit_cutoff: str | None = None,
) -> dict:
    if dataset["quality"]["rejected_rows"]:
        raise AnalyticsError("rejected_records", "Resolve rejected corpus rows first")
    if method not in ("manual", "keywords", "topic_model"):
        raise AnalyticsError("invalid_topic_method", "Unknown thematic evidence method")
    identifiers = [topic["topic_id"] for topic in topics]
    if not 1 <= len(topics) <= 100 or len(set(identifiers)) != len(identifiers):
        raise AnalyticsError("invalid_topics", "Use 1..100 unique topic identifiers")
    normalized = []
    for topic in topics:
        terms = [term.strip() for term in topic["terms"]]
        if (
            not topic["topic_id"].strip()
            or not topic["label"].strip()
            or not terms
            or any(not term for term in terms)
            or len({term.casefold() for term in terms}) != len(terms)
        ):
            raise AnalyticsError(
                "invalid_topics", "Topic labels and terms must be unique and nonempty"
            )
        normalized.append(
            {
                "topic_id": topic["topic_id"],
                "label": topic["label"].strip(),
                "terms": sorted(terms),
            }
        )
    documents = {doc["document_id"]: doc for doc in dataset["documents"]}
    if not set(assignments) <= documents.keys() or not set(assignments.values()) <= set(
        identifiers
    ):
        raise AnalyticsError("invalid_assignment", "Unknown document or topic")
    if method == "keywords":
        terms_by_topic = {
            topic["topic_id"]: {term.casefold() for term in topic["terms"]}
            for topic in normalized
        }
        if any(
            not terms_by_topic[topic_id]
            & {word.casefold() for word in documents[document_id]["keywords"]}
            for document_id, topic_id in assignments.items()
        ):
            raise AnalyticsError(
                "invalid_keyword_assignment",
                "Keyword assignments require an exact case-insensitive source keyword",
            )
    fit_ids = sorted(fit_document_ids or [])
    if len(fit_ids) != len(set(fit_ids)) or not set(fit_ids) <= documents.keys():
        raise AnalyticsError(
            "invalid_fit_documents", "Fit identifiers must be unique known documents"
        )
    if method == "topic_model":
        if (
            not model_version
            or not model_version.strip()
            or not fit_ids
            or not fit_cutoff
        ):
            raise AnalyticsError(
                "missing_model_provenance",
                "Declare model version, fit documents and cutoff",
            )
        parse_day(fit_cutoff)
        if any(
            not documents[doc_id]["publication_date"]
            or not documents[doc_id]["available_on"]
            or documents[doc_id]["publication_date"] > fit_cutoff
            or documents[doc_id]["available_on"] > fit_cutoff
            for doc_id in fit_ids
        ):
            raise AnalyticsError(
                "topic_temporal_leakage",
                "Fit documents must be published and available by cutoff",
            )
    elif model_version is not None or fit_ids or fit_cutoff is not None:
        raise AnalyticsError(
            "unexpected_model_provenance",
            "Manual/keyword evidence is not a fitted model",
        )
    definition = {
        "catalog_algorithm": "declared-topic-catalog-v1",
        "method": method,
        "model_version": model_version,
        "fit_document_ids": fit_ids,
        "fit_cutoff": fit_cutoff,
        "fit_corpus_sha256": (
            fingerprint([documents[identifier] for identifier in fit_ids])
            if fit_ids
            else None
        ),
        "topics": sorted(normalized, key=lambda topic: topic["topic_id"]),
    }
    content = {
        **definition,
        "topic_definition_version": fingerprint(definition),
        "dataset_version": dataset["dataset_version"],
        "data_kind": dataset["data_kind"],
        "assignments": dict(sorted(assignments.items())),
        "unassigned_document_ids": sorted(documents.keys() - assignments.keys()),
        "evidence_status": (
            "caller_declared; no topic model fitted or independently verified here"
        ),
        "curation_quality": dataset["quality"],
    }
    return {"catalog_version": fingerprint(content), **content}
