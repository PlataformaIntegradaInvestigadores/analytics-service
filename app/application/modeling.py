"""Optional topic runners. No corpus access, downloads or pickle deserialization."""

import importlib.metadata
import math
import warnings

from app.domain.common import AnalyticsError, fingerprint, parse_day


def validate_documents(documents, fit_ids, cutoff=None):
    identifiers = [d["document_id"] for d in documents]
    if (
        not 2 <= len(documents) <= 100000
        or len(set(identifiers)) != len(identifiers)
        or not fit_ids
        or len(set(fit_ids)) != len(fit_ids)
        or not set(fit_ids) <= set(identifiers)
        or any(
            not isinstance(d["text"], str)
            or not d["text"].strip()
            or len(d["text"]) > 100000
            for d in documents
        )
    ):
        raise AnalyticsError(
            "invalid_model_documents", "Unique bounded texts/fit IDs required"
        )
    if cutoff is not None:
        parse_day(cutoff)
        for doc in documents:
            if doc["document_id"] in fit_ids:
                for field in ("publication_date", "available_on"):
                    if not doc.get(field):
                        raise AnalyticsError(
                            "unknown_availability", "Historical availability required"
                        )
                    parse_day(doc[field])
                    if doc[field] > cutoff:
                        raise AnalyticsError(
                            "temporal_leakage", "Fit document exceeds cutoff"
                        )
    return sorted(
        (d for d in documents if d["document_id"] in fit_ids),
        key=lambda d: d["document_id"],
    )


def fit_nmf(
    documents,
    fit_ids,
    *,
    workset_id,
    topics=2,
    seed=42,
    max_features=5000,
    max_iter=300,
    cutoff=None,
    purpose="technical",
    software=None,
    research_protocol=None,
    vectorizer_options=None,
    initializer="nndsvda",
):
    if purpose not in ("technical", "research"):
        raise AnalyticsError(
            "research_use_pending", "Final research use is not authorized here"
        )
    if purpose == "research":
        protocol = research_protocol or {}
        if (
            protocol.get("temporal_mode") != "publication_year_reconstruction"
            or not isinstance(protocol.get("approval_reference"), str)
            or not protocol["approval_reference"].strip()
            or type(protocol.get("fit_end_year")) is not int
            or not protocol.get("source_version")
            or cutoff is not None
        ):
            raise AnalyticsError(
                "invalid_research_protocol", "Explicit reconstruction protocol required"
            )
        research_fit_ids = set(fit_ids)
        for doc in documents:
            if doc["document_id"] in research_fit_ids:
                if not doc.get("publication_date"):
                    raise AnalyticsError(
                        "invalid_research_protocol", "Publication year required"
                    )
                if parse_day(doc["publication_date"]).year > protocol["fit_end_year"]:
                    raise AnalyticsError(
                        "temporal_leakage", "Topic fit exceeds protocol year"
                    )
    fit = validate_documents(documents, fit_ids, cutoff)
    if (
        not isinstance(workset_id, str)
        or len(workset_id) != 64
        or any(c not in "0123456789abcdef" for c in workset_id)
        or type(topics) is not int
        or not 2 <= topics <= min(100, len(fit))
        or type(seed) is not int
        or not 0 <= seed < 2**32
        or type(max_features) is not int
        or not 10 <= max_features <= 20000
        or type(max_iter) is not int
        or not 10 <= max_iter <= 1000
        or initializer not in ("nndsvda", "random")
    ):
        raise AnalyticsError(
            "invalid_model_config", "Invalid bounded NMF configuration"
        )
    from sklearn.decomposition import NMF
    from sklearn.feature_extraction.text import TfidfVectorizer
    from threadpoolctl import threadpool_limits

    options = vectorizer_options or {}
    if set(options) - {
        "min_df",
        "max_df",
        "stop_words",
        "strip_accents",
        "token_pattern",
    }:
        raise AnalyticsError("invalid_vectorizer", "Unsupported vectorizer options")
    vectorizer = TfidfVectorizer(max_features=max_features, **options)
    try:
        matrix = vectorizer.fit_transform([d["text"] for d in fit])
    except ValueError as exc:
        raise AnalyticsError("empty_vocabulary", "No usable vocabulary") from exc
    if matrix.shape[1] < topics:
        raise AnalyticsError("insufficient_vocabulary", "Fewer terms than topics")
    with threadpool_limits(limits=1), warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        model = NMF(
            n_components=topics,
            init=initializer,
            random_state=seed,
            max_iter=max_iter,
            tol=1e-4,
        )
        model.fit(matrix)
    content = {
        "format": "nmf-json-v1",
        "software_sha256": software or {},
        "method": "tfidf-nmf",
        "workset_id": workset_id,
        "fit_ids": [d["document_id"] for d in fit],
        "fit_sha256": fingerprint(fit),
        "cutoff": cutoff,
        "purpose": purpose,
        "temporal_status": (
            "verified_declared_availability" if cutoff else "not_temporal_validation"
        ),
        "configuration": {
            "topics": topics,
            "seed": seed,
            "max_features": max_features,
            "max_iter": max_iter,
            "tol": 1e-4,
        },
        "versions": {
            p: importlib.metadata.version(p) for p in ("scikit-learn", "numpy", "scipy")
        },
        "vocabulary": vectorizer.vocabulary_,
        "idf": vectorizer.idf_.tolist(),
        "components": model.components_.tolist(),
        "iterations": int(model.n_iter_),
        "warnings": [str(w.message) for w in caught],
        "training_reconstruction_error": float(model.reconstruction_err_),
        "evaluation": "technical_training_diagnostic_not_final_quality_metric",
    }
    # Vocabulary values may be numpy integer scalars.
    content["vocabulary"] = {k: int(v) for k, v in content["vocabulary"].items()}
    if purpose == "research":
        content["research_protocol"] = research_protocol
        content["temporal_status"] = "publication_year_reconstruction_not_index_replay"
        content["evaluation"] = (
            "empirical_research_candidate_not_final_thesis_validation"
        )
    if options:
        content["configuration"]["vectorizer"] = options
    if initializer != "nndsvda":
        content["configuration"]["initializer"] = initializer
    return {"model_id": fingerprint(content), **content}


def infer_nmf(artifact, documents):
    import numpy as np
    from sklearn.decomposition import NMF
    from sklearn.feature_extraction.text import CountVectorizer, TfidfTransformer
    from threadpoolctl import threadpool_limits

    content = {k: v for k, v in artifact.items() if k != "model_id"}
    if (
        fingerprint(content) != artifact["model_id"]
        or artifact["format"] != "nmf-json-v1"
        or artifact["versions"]["scikit-learn"]
        != importlib.metadata.version("scikit-learn")
    ):
        raise AnalyticsError("model_integrity", "Model content/version mismatch")
    if (
        not documents
        or len(documents) > 100000
        or len({d["document_id"] for d in documents}) != len(documents)
        or any(
            not isinstance(d["text"], str)
            or not d["text"].strip()
            or len(d["text"]) > 100000
            for d in documents
        )
    ):
        raise AnalyticsError(
            "invalid_inference", "Unique bounded nonblank documents required"
        )
    vectorizer = CountVectorizer(
        vocabulary=artifact["vocabulary"],
        **artifact["configuration"].get("vectorizer", {}),
    )
    transformer = TfidfTransformer()
    transformer.idf_ = np.array(artifact["idf"])
    matrix = transformer.transform(vectorizer.transform([d["text"] for d in documents]))
    model = NMF(
        n_components=len(artifact["components"]),
        init="custom",
        max_iter=artifact["configuration"]["max_iter"],
        tol=1e-4,
        random_state=artifact["configuration"]["seed"],
    )
    model.components_ = np.array(artifact["components"])
    model.n_features_in_ = len(artifact["idf"])
    with threadpool_limits(limits=1):
        weights = model.transform(matrix)
    return [
        {
            "document_id": d["document_id"],
            "topic_id": f"topic-{int(row.argmax())}" if row.sum() else None,
            "weights": [float(x) for x in row],
            "status": "assigned" if row.sum() else "out_of_vocabulary",
            "model_id": artifact["model_id"],
        }
        for d, row in zip(documents, weights, strict=True)
    ]


def bertopic_capability():
    packages = {}
    for package in ("bertopic", "sentence-transformers", "umap-learn", "hdbscan"):
        try:
            packages[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            packages[package] = None
    return {
        "packages": packages,
        "available": all(packages.values()),
        "downloads": "disabled; supply local embeddings explicitly",
        "viability": "requires_bounded_local_embedding_benchmark",
    }


def fit_bertopic(documents, fit_ids, embeddings, *, cutoff=None):
    fit = validate_documents(documents, fit_ids, cutoff)
    if (
        len(embeddings) != len(fit)
        or not embeddings
        or not embeddings[0]
        or any(
            len(row) != len(embeddings[0])
            or any(not isinstance(x, (float, int)) or not math.isfinite(x) for x in row)
            for row in embeddings
        )
    ):
        raise AnalyticsError(
            "invalid_embeddings", "Supply finite rows in sorted fit-ID order"
        )
    if not bertopic_capability()["available"]:
        raise AnalyticsError(
            "bertopic_unavailable", "Optional local dependencies are absent"
        )
    import numpy as np
    from bertopic import BERTopic
    from umap import UMAP

    model = BERTopic(
        embedding_model=None,
        umap_model=UMAP(
            random_state=42,
            n_neighbors=min(15, len(fit) - 1),
            n_components=min(5, max(1, len(fit) - 2)),
            init="random",
        ),
    )
    labels, _ = model.fit_transform([d["text"] for d in fit], np.asarray(embeddings))
    return {
        "method": "bertopic",
        "fit_ids": [d["document_id"] for d in fit],
        "labels": [int(x) for x in labels],
        "outlier_label": -1,
        "embedding_sha256": fingerprint(embeddings),
        "cutoff": cutoff,
        "purpose": "technical",
        "persistence": "native_model_not_exported",
    }
