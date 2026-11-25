"""Composition of real-text topic comparisons and a pending human-review catalog."""

import json
from html.parser import HTMLParser

from app.application.modeling import fit_nmf, infer_nmf
from app.data.documents import read_database
from app.data.models import ModelStore
from app.domain.common import AnalyticsError, canonical_json, fingerprint
from app.research_execution import topic_quality


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def clean_markup(text):
    for _ in range(2):
        parser = _Text()
        parser.feed(text)
        parser.close()
        text = " ".join(parser.parts)
    return " ".join(text.split())


def fit_lda(documents, template, components=8):
    import numpy as np
    from sklearn.decomposition import LatentDirichletAllocation
    from sklearn.feature_extraction.text import CountVectorizer
    from threadpoolctl import threadpool_limits

    options = template["configuration"]["vectorizer"]
    vectorizer = CountVectorizer(max_features=3000, **options)
    x = vectorizer.fit_transform([d["text"] for d in documents])
    with threadpool_limits(limits=1):
        model = LatentDirichletAllocation(
            n_components=components,
            max_iter=20,
            learning_method="batch",
            random_state=42,
            n_jobs=1,
        ).fit(x)
    content = {
        "format": "count-lda-json-v1",
        "method": "count-lda",
        "purpose": "research",
        "vocabulary": {k: int(v) for k, v in vectorizer.vocabulary_.items()},
        "components": model.components_.tolist(),
        "exp_dirichlet_component": model.exp_dirichlet_component_.tolist(),
        "doc_topic_prior": float(model.doc_topic_prior_),
        "topic_word_prior": float(model.topic_word_prior_),
        "configuration": {
            "topics": components,
            "seed": 42,
            "max_iter": 20,
            "max_features": 3000,
            "vectorizer": options,
        },
        "versions": template["versions"],
        "fit_ids": [d["document_id"] for d in documents],
        "fit_sha256": fingerprint(documents),
        "research_protocol": template["research_protocol"],
    }
    artifact = {"model_id": fingerprint(content), **content}
    # Inert persistence must reproduce the actual fitted transform.
    if not np.allclose(
        model.transform(x[:3]), infer_lda(artifact, documents[:3])[0], atol=1e-10
    ):
        raise AnalyticsError(
            "lda_roundtrip", "LDA transform changed after JSON reconstruction"
        )
    return artifact


def infer_lda(artifact, documents):
    import numpy as np
    from sklearn.decomposition import LatentDirichletAllocation
    from sklearn.feature_extraction.text import CountVectorizer
    from threadpoolctl import threadpool_limits

    content = {k: v for k, v in artifact.items() if k != "model_id"}
    if fingerprint(content) != artifact["model_id"]:
        raise AnalyticsError("model_integrity", "LDA artifact changed")
    vectorizer = CountVectorizer(
        vocabulary=artifact["vocabulary"], **artifact["configuration"]["vectorizer"]
    )
    x = vectorizer.transform([d["text"] for d in documents])
    model = LatentDirichletAllocation(
        n_components=len(artifact["components"]), random_state=42, n_jobs=1
    )
    model.components_ = np.asarray(artifact["components"])
    model.exp_dirichlet_component_ = np.asarray(artifact["exp_dirichlet_component"])
    model.doc_topic_prior_ = artifact["doc_topic_prior"]
    model.topic_word_prior_ = artifact["topic_word_prior"]
    model.n_features_in_ = len(artifact["vocabulary"])
    with threadpool_limits(limits=1):
        weights = model.transform(x)
    valid = np.asarray(x.getnnz(axis=1)) > 0
    return weights, valid


def summarize_model(model, documents):
    import numpy as np

    quality = topic_quality(model, documents)
    if model["method"] == "count-lda":
        weights, valid = infer_lda(model, documents)
    else:
        assigned = infer_nmf(model, documents)
        weights = np.asarray([a["weights"] for a in assigned])
        valid = weights.sum(axis=1) > 0
    sums = weights.sum(axis=1)
    confidence = weights.max(axis=1) / np.where(sums > 0, sums, 1)
    components = np.asarray(model["components"])
    norms = np.linalg.norm(components, axis=1)
    normalized = components / np.where(norms[:, None] > 0, norms[:, None], 1)
    similarities = normalized @ normalized.T
    np.fill_diagonal(similarities, 0)
    sizes = np.bincount(
        weights[valid].argmax(axis=1), minlength=len(components)
    ).tolist()
    return (
        {
            **quality,
            "assigned_documents": int(valid.sum()),
            "coverage": float(valid.mean()),
            "low_dominance_fraction": (
                float((confidence[valid] < 0.5).mean()) if valid.any() else None
            ),
            "assignment_interpretation": (
                "Hard argmax of normalized weights; not supervised truth or c"
                "alibrated probability"
            ),
            "topic_sizes": sizes,
            "maximum_pairwise_component_cosine": float(similarities.max()),
        },
        weights,
        valid,
    )


def stability(reference, alternatives):
    import numpy as np
    from scipy.optimize import linear_sum_assignment

    a = np.asarray(reference["components"])
    a = a / np.maximum(np.linalg.norm(a, axis=1, keepdims=True), 1e-30)
    results = []
    for model in alternatives:
        if model["vocabulary"] != reference["vocabulary"]:
            raise AnalyticsError(
                "incompatible_vocabulary", "Align only identical fitted vocabularies"
            )
        b = np.asarray(model["components"])
        b = b / np.maximum(np.linalg.norm(b, axis=1, keepdims=True), 1e-30)
        similarity = a @ b.T
        left, right = linear_sum_assignment(-similarity)
        overlap = []
        for i, j in zip(left, right, strict=True):
            x = set(np.argsort(a[i])[-10:].tolist())
            y = set(np.argsort(b[j])[-10:].tolist())
            overlap.append(len(x & y) / len(x | y))
        results.append(
            {
                "model_id": model["model_id"],
                "seed": model["configuration"]["seed"],
                "mean_matched_cosine": float(similarity[left, right].mean()),
                "mean_top10_jaccard": float(np.mean(overlap)),
            }
        )
    return {
        "method": (
            "Hungarian alignment across actual NMF fits; identical traini"
            "ng documents"
        ),
        "reference_initializer": "nndsvda",
        "alternative_initializer": "random",
        "results": results,
    }


def compare_topics(corpus, prepared, base_models, output, protocol, software):
    with read_database(corpus) as db:
        source = {
            identifier: json.loads(encoded)
            for identifier, encoded in db.execute(
                "SELECT article_id,document FROM articles"
            )
        }
    with read_database(prepared) as db:
        # The previously observed test texts are explicitly outside this comparison.
        documents = [
            {
                "document_id": identifier,
                "article_id": article,
                "year": year,
                "publication_date": source[article]["publication_date"],
                "text": text,
            }
            for identifier, article, year, text in db.execute(
                (
                    "SELECT document_id,article_id,year,text FROM prepared WHERE "
                    "year<=? ORDER BY document_id"
                ),
                (protocol["validation_end"],),
            )
        ]
    fit = [d for d in documents if d["year"] <= protocol["topic_fit_end"]]
    validation = [d for d in documents if d["year"] > protocol["topic_fit_end"]]
    cleaned = [{**d, "text": clean_markup(d["text"])} for d in documents]
    clean_fit = [d for d in cleaned if d["year"] <= protocol["topic_fit_end"]]
    clean_validation = [d for d in cleaned if d["year"] > protocol["topic_fit_end"]]
    with read_database(base_models) as db:
        old = [
            json.loads(payload)
            for payload, in db.execute("SELECT payload FROM fitted_models ORDER BY id")
        ]
    # Stored payloads omit their content-derived ID.
    old = [{"model_id": fingerprint(m), **m} for m in old]
    reference = next(m for m in old if len(m["components"]) == 8)
    models = [(f"nmf_raw_k{len(m['components'])}", m, fit, validation) for m in old]
    options = reference["configuration"]["vectorizer"]
    store = ModelStore(output / "new-topic-models.sqlite")
    kwargs = {
        "workset_id": fingerprint(
            [(d["document_id"], fingerprint(d["text"])) for d in clean_fit]
        ),
        "topics": 8,
        "max_iter": 500,
        "purpose": "research",
        "research_protocol": reference["research_protocol"],
        "vectorizer_options": options,
        "max_features": 5000,
        "software": software,
    }
    clean_model = fit_nmf(
        cleaned, [d["document_id"] for d in clean_fit], seed=42, **kwargs
    )
    store.save(clean_model)
    models.append(("nmf_html_text_k8", clean_model, clean_fit, clean_validation))
    lda = fit_lda(clean_fit, reference)
    (output / "lda-model.json").write_text(canonical_json(lda), encoding="utf-8")
    models.append(("lda_html_text_k8", lda, clean_fit, clean_validation))
    replicas = []
    for seed in (43, 44):
        replica = fit_nmf(
            cleaned,
            [d["document_id"] for d in clean_fit],
            seed=seed,
            initializer="random",
            **kwargs,
        )
        store.save(replica)
        replicas.append(replica)
    summaries, catalog = [], []
    flags = {"inf", "sup", "sub", "amp", "nbsp", "fig", "et", "al"}
    for name, model, training, val in models:
        train_quality, weights, valid = summarize_model(model, training)
        val_quality, _, _ = summarize_model(model, val)
        summaries.append(
            {
                "candidate_id": name,
                "model_id": model["model_id"],
                "method": model["method"],
                "training": train_quality,
                "validation": val_quality,
            }
        )
        for index, topic in enumerate(train_quality["topics"]):
            # Selection uses training texts only; review is pending, never invented.
            ranked = sorted(
                (
                    i
                    for i in range(len(training))
                    if valid[i] and weights[i].argmax() == index
                ),
                key=lambda i: (-float(weights[i, index]), training[i]["document_id"]),
            )[:3]
            representatives = [
                {
                    "article_id": training[i]["article_id"],
                    "year": training[i]["year"],
                    "title": source[training[i]["article_id"]]["title"],
                    "excerpt": training[i]["text"][:400],
                    "weight": float(weights[i, index]),
                }
                for i in ranked
            ]
            catalog.append(
                {
                    "candidate_id": name,
                    "model_id": model["model_id"],
                    **topic,
                    "term_review_flags": [
                        t for t in topic["terms"] if len(t) <= 2 or t in flags
                    ],
                    "flag_interpretation": (
                        "Needs domain context; short terms can be legitimate"
                    ),
                    "representatives": representatives,
                    "human_label": None,
                    "human_review_status": "pending",
                }
            )
    selected = max(
        summaries,
        key=lambda s: (
            s["validation"]["mean_npmi"],
            s["validation"]["term_diversity"],
            s["candidate_id"],
        ),
    )
    return {
        "candidates": summaries,
        "selected_for_review_by_validation": selected["candidate_id"],
        "selection_rule": (
            "Highest validation document NPMI, then diversity; no final s"
            "cientific model promotion"
        ),
        "validation_years": [protocol["topic_fit_end"] + 1, protocol["validation_end"]],
        "previous_test_texts_used": False,
        "fit_documents": len(fit),
        "validation_documents": len(validation),
        "html_changed_training_documents": sum(
            a["text"] != b["text"] for a, b in zip(fit, clean_fit, strict=True)
        ),
        "stability": stability(clean_model, replicas),
        "bertopic_status": (
            "Existing optional capability remains pending embeddings/reso"
            "urces; LDA is an additional bounded candidate"
        ),
        "classification_status": (
            "No validated labels supplied; no supervised accuracy/F1 inve" "nted"
        ),
        "human_review_status": "pending",
        "source_keywords_used_as_ground_truth": False,
    }, catalog
