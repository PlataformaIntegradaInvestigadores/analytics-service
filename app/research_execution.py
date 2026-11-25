"""Composition root: frozen topics, annual rolling evaluation and exact XAI.

All artifacts are local. Publication-year reconstruction is not an index replay.
"""

import importlib.metadata
import json
import math
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from contextlib import closing
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path

from app.application.modeling import fit_nmf, infer_nmf
from app.core.provenance import sha256_file, source_files
from app.data.documents import read_database
from app.data.models import ModelStore
from app.domain.annual_prediction import (
    FEATURES,
    annual_rows,
    explain_prediction,
    metrics,
    train_ridge,
)
from app.domain.common import AnalyticsError, canonical_json, fingerprint
from app.domain.text import prepare_text
from app.schemas.study import StudyProtocol


def prepare(corpus, protocol, destination):
    """Keep earliest publication of repeated text; persist every inclusion decision."""
    documents, decisions, seen = [], [], set()
    with read_database(corpus) as db:
        origin = json.loads(db.execute("SELECT payload FROM manifest").fetchone()[0])
        if origin.get("use_scope") != "research_authorized_as_declared":
            raise AnalyticsError(
                "research_authorization_missing",
                "Use the research snapshot, not development data",
            )
        source_years = dict(
            db.execute(
                "SELECT CAST(year AS INTEGER),COUNT(*) FROM articles GROUP BY year"
            )
        )
        for identifier, encoded in db.execute(
            "SELECT article_id,document FROM articles ORDER BY "
            "publication_date,article_id"
        ):
            d = json.loads(encoded)
            year = int(d["publication_date"][:4])
            reason = None
            text = prepare_text(d["title"], d["abstract"])
            if not protocol.start_year <= year <= protocol.test_end:
                reason = "outside_prespecified_years"
            elif not text["has_abstract"]:
                reason = "missing_abstract"
            elif text["token_count"] < 5:
                reason = "insufficient_tokens"
            elif text["duplicate_key"] in seen:
                reason = "later_exact_normalized_text"
            if reason is None:
                seen.add(text["duplicate_key"])
                documents.append(
                    {
                        "document_id": d["document_id"],
                        "article_id": identifier,
                        "publication_date": d["publication_date"],
                        "text": text["text"],
                        "year": year,
                    }
                )
            decisions.append(
                (identifier, year, reason or "included", text["text_sha256"])
            )
    required = set(range(protocol.start_year, protocol.test_end + 1))
    if not required <= set(source_years) or not required <= {
        d["year"] for d in documents
    }:
        raise AnalyticsError(
            "unobserved_year", "Do not silently turn absent snapshot years into zero"
        )
    content = {
        "source_version": origin["source_version"],
        "decisions_sha256": fingerprint(decisions),
        "protocol": protocol.model_dump(),
        "ordering": "publication_date,article_id",
        "text": (
            "NFKC title + abstract; min 5 Unicode tokens; no lemmatization or "
            "inferred language"
        ),
        "duplicates": (
            "earliest date/ID exact normalized text; not DOI-based publication merging"
        ),
    }
    workset_id = fingerprint(content)
    with closing(sqlite3.connect(destination)) as db, db:
        db.execute(
            "CREATE TABLE decisions (article_id TEXT,year INTEGER,decision "
            "TEXT,text_sha256 TEXT)"
        )
        db.executemany("INSERT INTO decisions VALUES (?,?,?,?)", decisions)
        db.execute(
            "CREATE TABLE prepared (document_id TEXT PRIMARY KEY,article_id "
            "TEXT,year INTEGER,text TEXT)"
        )
        db.executemany(
            "INSERT INTO prepared VALUES (?,?,?,?)",
            [
                (d["document_id"], d["article_id"], d["year"], d["text"])
                for d in documents
            ],
        )
        db.execute("CREATE TABLE manifest (payload TEXT)")
        db.execute(
            "INSERT INTO manifest VALUES (?)",
            (canonical_json({"workset_id": workset_id, **content}),),
        )
    return (
        documents,
        origin,
        {
            "workset_id": workset_id,
            "input_articles": len(decisions),
            "included": len(documents),
            "decisions": dict(Counter(r[2] for r in decisions)),
            "source_year_counts": source_years,
            "text_policy": content["text"],
            "duplicate_policy": content["duplicates"],
        },
    )


def topic_quality(model, documents, top_n=10):
    """Document-cooccurrence NPMI on supplied real texts, with frozen vocabulary."""
    import numpy as np
    from sklearn.feature_extraction.text import CountVectorizer

    vocabulary = model["vocabulary"]
    options = model["configuration"].get("vectorizer", {})
    binary = CountVectorizer(vocabulary=vocabulary, binary=True, **options).transform(
        [d["text"] for d in documents]
    )
    # Cast before multiplication: boolean/8-bit sparse products would lose counts.
    binary = binary.astype(np.int64)
    terms = [""] * len(vocabulary)
    for word, index in vocabulary.items():
        terms[index] = word
    topics = []
    all_words = []
    for i, weights in enumerate(model["components"]):
        ids = sorted(range(len(weights)), key=lambda j: (-weights[j], j))[:top_n]
        small = binary[:, ids]
        freq = np.asarray(small.sum(axis=0)).ravel() / len(documents)
        pairs = (small.T @ small).toarray() / len(documents)
        values = []
        for a, b in combinations(range(len(ids)), 2):
            p = float(pairs[a, b])
            values.append(
                math.log(p / (freq[a] * freq[b])) / -math.log(p)
                if 0 < p < 1
                else (0.0 if p == 1 else -1.0)
            )
        words = [terms[j] for j in ids]
        all_words.extend(words)
        topics.append(
            {
                "topic_id": f"topic-{i}",
                "terms": words,
                "npmi": sum(values) / len(values),
            }
        )
    return {
        "document_count": len(documents),
        "npmi_definition": (
            "mean pairwise normalized PMI over top 10 terms; zero cooccurrence=-1"
        ),
        "mean_npmi": sum(t["npmi"] for t in topics) / len(topics),
        "term_diversity": len(set(all_words)) / len(all_words),
        "topics": topics,
    }


def topic_series(documents, assignments, protocol):
    totals = Counter(d["year"] for d in documents)
    counts = Counter()
    unassigned = Counter()
    representatives = defaultdict(list)
    for d, a in zip(documents, assignments, strict=True):
        if d["document_id"] != a["document_id"]:
            raise AnalyticsError(
                "assignment_order", "Document assignment identity mismatch"
            )
        if a["topic_id"] is None:
            unassigned[d["year"]] += 1
        else:
            counts[a["topic_id"], d["year"]] += 1
            # IDs only; original abstracts remain private in the prepared snapshot.
            representatives[a["topic_id"]].append((max(a["weights"]), d["article_id"]))
    topic_ids = sorted(
        {a["topic_id"] for a in assignments if a["topic_id"] is not None}
    )
    series = {
        topic: [
            {
                "year": year,
                "count": counts[topic, year],
                "denominator": totals[year],
                "share": counts[topic, year] / totals[year],
                "unassigned_documents": unassigned[year],
                "coverage": "observed_prepared_snapshot_not_population",
            }
            for year in range(protocol.start_year, protocol.test_end + 1)
        ]
        for topic in topic_ids
    }
    return series, {
        topic: [v[1] for v in sorted(values, reverse=True)[:3]]
        for topic, values in representatives.items()
    }


def _evaluate(rows, start, end, alpha, reference):
    records = []
    models = []
    for year in range(start, end + 1):
        training = [r for r in rows if r["year"] < year and r["observed"] is not None]
        model = train_ridge(training, alpha, reference)
        models.append(model)
        for r in rows:
            if r["year"] == year:
                records.append(
                    {"topic_id": r["topic_id"], **explain_prediction(model, r)}
                )
    return records, models


def _summary(records):
    return {
        "ridge": metrics(
            [r["observed"] for r in records], [r["prediction"] for r in records]
        ),
        "last_value": metrics(
            [r["observed"] for r in records],
            [r["baseline_last_value"] for r in records],
        ),
    }


def forecast_study(series, protocol):
    rows = []
    for topic, points in sorted(series.items()):
        rows.extend({"topic_id": topic, **r} for r in annual_rows(points))
    initial = [r for r in rows if r["year"] <= protocol.topic_fit_end]
    reference = [
        sum(r["features"][j] for r in initial) / len(initial) for j in range(4)
    ]
    candidates = []
    for alpha in protocol.ridge_alphas:
        validation, _ = _evaluate(
            rows, protocol.topic_fit_end + 1, protocol.validation_end, alpha, reference
        )
        candidates.append({"alpha": alpha, **_summary(validation)})
    chosen = min(candidates, key=lambda c: (c["ridge"]["mae"], c["alpha"]))
    alpha = chosen["alpha"]
    validation, validation_models = _evaluate(
        rows, protocol.topic_fit_end + 1, protocol.validation_end, alpha, reference
    )
    test, test_models = _evaluate(
        rows, protocol.validation_end + 1, protocol.test_end, alpha, reference
    )
    train = [r for r in rows if r["observed"] is not None]
    final_model = train_ridge(train, alpha, reference)
    forecasts = [
        {"topic_id": r["topic_id"], **explain_prediction(final_model, r)}
        for r in rows
        if r["observed"] is None
    ]
    # Compare expanding-history refits on identical observed inputs.
    drift = []
    for year in range(protocol.validation_end + 1, protocol.test_end + 1):
        previous = train_ridge(
            [r for r in rows if r["year"] < year - 1], alpha, reference
        )
        current = next(m for m in test_models if m["trained_through"] == year - 1)
        for r in rows:
            if r["year"] == year:
                a = explain_prediction(previous, r)["explanation"]["contributions"]
                b = explain_prediction(current, r)["explanation"]["contributions"]
                drift.append(sum(abs(x - y) for x, y in zip(a, b, strict=True)))
    global_importance = [
        {
            "feature": name,
            "mean_absolute_attribution": sum(
                abs(r["explanation"]["contributions"][i]) for r in test
            )
            / len(test),
        }
        for i, name in enumerate(FEATURES)
    ]
    return {
        "method": "pooled_ridge_log1p",
        "features": FEATURES,
        "selection": (
            "lowest expanding validation MAE among prespecified ridge alphas; "
            "last-value reference reported separately"
        ),
        "validation_candidates": candidates,
        "selected_alpha": alpha,
        "validation": _summary(validation),
        "test": _summary(test),
        "test_records": test,
        "validation_records": validation,
        "forecasts": forecasts,
        "global_explanation": {
            "scope": "global",
            "sample": "held-out rolling test predictions",
            "output_scale": "log1p_snapshot_article_count",
            "features": global_importance,
        },
        "fidelity": {
            "metric": "max_absolute_additivity_residual",
            "value": max(
                r["explanation"]["additivity_residual"] for r in [*test, *forecasts]
            ),
            "scope": "exact model-output reconstruction, not causal/human fidelity",
        },
        "stability": {
            "metric": "mean_L1_attribution_drift_between_real_expanding_refits",
            "value": sum(drift) / len(drift),
            "n": len(drift),
            "reference": "fixed training background through topic-fit year",
            "interpretation": (
                "Observed change under adding an actual year; no universal "
                "stability threshold or synthetic noise claimed"
            ),
        },
        "intervals": None,
        "forecast_interpretation": (
            "One-step retrospective projection after test_end, not a "
            "current-calendar forecast or population coverage claim"
        ),
    }, [*validation_models, *test_models, final_model]


def run_study(corpus, output, protocol):
    protocol = StudyProtocol.model_validate(protocol)
    corpus, output = Path(corpus).resolve(), Path(output).resolve()
    repository = Path(__file__).resolve().parents[1]
    if (
        output.is_relative_to(repository)
        or output.exists()
        or output == corpus
        or output.is_relative_to(corpus)
    ):
        raise AnalyticsError(
            "unsafe_study_output", "Choose a new directory outside the repository"
        )
    before = sha256_file(corpus)
    software = source_files()
    output.mkdir(parents=True, exist_ok=False)
    (output / "protocol.json").write_text(
        canonical_json(protocol.model_dump()), encoding="utf-8"
    )

    def progress(stage):
        (output / "progress.json").write_text(
            canonical_json({"stage": stage}), encoding="utf-8"
        )
        print(canonical_json({"stage": stage}), flush=True)

    progress("preparing_real_corpus")
    documents, origin, prepared = prepare(corpus, protocol, output / "prepared.sqlite")
    fit = [d for d in documents if d["year"] <= protocol.topic_fit_end]
    research_protocol = {
        "temporal_mode": "publication_year_reconstruction",
        "approval_reference": protocol.approval_reference,
        "fit_end_year": protocol.topic_fit_end,
        "source_version": origin["source_version"],
    }
    spanish = (
        "de la el los las del y en con por para una uno un que se su sus "
        "al como es son más no entre sobre este esta estos estas desde "
        "hasta también a o e u lo les le las muy sin según"
    ).split()
    from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS

    stopwords = sorted(
        set(ENGLISH_STOP_WORDS)
        | set(spanish)
        | {
            "copyright",
            "reserved",
            "rights",
            "elsevier",
            "springer",
            "license",
            "licence",
        }
    )
    stopwords = sorted(
        {
            "".join(
                c
                for c in unicodedata.normalize("NFKD", word)
                if not unicodedata.combining(c)
            )
            for word in stopwords
        }
    )
    options = {
        "min_df": protocol.min_df,
        "max_df": 0.90,
        "stop_words": stopwords,
        "strip_accents": "unicode",
        "token_pattern": r"(?u)\b[^\W\d_][^\W\d_]+\b",
    }
    candidates = []
    store = ModelStore(output / "models.sqlite")
    for topics in protocol.topic_candidates:
        progress("fit_real_nmf_" + str(topics))
        model = fit_nmf(
            documents,
            [d["document_id"] for d in fit],
            workset_id=prepared["workset_id"],
            topics=topics,
            seed=protocol.seed,
            max_features=protocol.max_features,
            max_iter=500,
            purpose="research",
            research_protocol=research_protocol,
            vectorizer_options=options,
            software=software,
        )
        store.save(model)
        quality = topic_quality(model, fit)
        candidates.append(
            {
                "topics": topics,
                "model_id": model["model_id"],
                "mean_npmi": quality["mean_npmi"],
                "term_diversity": quality["term_diversity"],
                "iterations": model["iterations"],
                "warnings": model["warnings"],
            }
        )
    selected = max(
        candidates, key=lambda c: (c["mean_npmi"], c["term_diversity"], -c["topics"])
    )
    model = store.load(selected["model_id"])
    progress("infer_frozen_topics_real_texts")
    assignments = infer_nmf(model, documents)
    with closing(sqlite3.connect(output / "prepared.sqlite")) as db, db:
        db.execute(
            "CREATE TABLE assignments(document_id TEXT PRIMARY KEY,topic_id "
            "TEXT,weights TEXT)"
        )
        db.executemany(
            "INSERT INTO assignments VALUES (?,?,?)",
            [
                (a["document_id"], a["topic_id"], canonical_json(a["weights"]))
                for a in assignments
            ],
        )
    series, representatives = topic_series(documents, assignments, protocol)
    progress("annual_forecasting_and_exact_attributions")
    forecast, regressors = forecast_study(series, protocol)
    quality = topic_quality(model, fit)
    heldout_quality = topic_quality(
        model, [d for d in documents if d["year"] > protocol.validation_end]
    )
    snapshot_unchanged = before == sha256_file(corpus)
    if not snapshot_unchanged:
        raise AnalyticsError(
            "corpus_source_changed", "Snapshot changed during experiment"
        )
    identity = {
        "source_snapshot_sha256": before,
        "source_version": origin["source_version"],
        "protocol": protocol.model_dump(),
        "software_sha256": software,
        "versions": {
            k: importlib.metadata.version(k) for k in ("scikit-learn", "numpy", "scipy")
        },
    }
    report = {
        "run_id": fingerprint(identity),
        "identity": identity,
        "executed_at": datetime.now(UTC).isoformat(),
        "status": "empirical_preliminary_study",
        "data_kind": "empirical",
        "source_articles": origin["articles"],
        "source_unchanged": True,
        "temporal_mode": "publication_year_reconstruction_not_historical_index_replay",
        "preparation": prepared,
        "protocol": protocol.model_dump(),
        "topic_model_id": model["model_id"],
        "topic_candidates": candidates,
        "topic_selection": (
            "maximum training document-cooccurrence NPMI; diversity then "
            "smaller k break ties; test not used"
        ),
        "topic_quality_train": {k: v for k, v in quality.items() if k != "topics"},
        "topic_quality_test": {
            k: v for k, v in heldout_quality.items() if k != "topics"
        },
        "topics": [
            {**t, "representative_article_ids": representatives.get(t["topic_id"], [])}
            for t in quality["topics"]
        ],
        "series": series,
        "prediction": forecast,
        "limitations": [
            "Text modeling uses titles and abstracts.",
            (
                "Corpus flag and author/affiliation count semantics not assumed or "
                "used as predictive features"
            ),
            (
                "Annual series describe prepared snapshot, not complete scientific "
                "production"
            ),
            "No first-indexed dates supplied; publication-year reconstruction only",
            "Topic names are top terms, not validated knowledge-area labels",
            (
                "No causal claims, confidence intervals, human usability or "
                "actionability results"
            ),
            "No institutional gateway/identity deployment certified",
        ],
        "preprocessing": {
            "stop_words": (
                "prespecified sklearn English + listed Spanish function words and "
                "publication boilerplate; not language detection"
            ),
            "stopwords_sha256": fingerprint(stopwords),
            "stemming_or_lemmatization": False,
        },
    }
    report["report_sha256"] = fingerprint(report)
    with closing(sqlite3.connect(output / "study.sqlite")) as db, db:
        db.execute("CREATE TABLE study (id TEXT PRIMARY KEY,payload TEXT)")
        db.execute(
            "INSERT INTO study VALUES (?,?)", (report["run_id"], canonical_json(report))
        )
        db.execute("CREATE TABLE regressors (id TEXT PRIMARY KEY,payload TEXT)")
        db.executemany(
            "INSERT OR IGNORE INTO regressors VALUES (?,?)",
            [(m["model_id"], canonical_json(m)) for m in regressors],
        )
    (output / "report.json").write_text(canonical_json(report), encoding="utf-8")
    progress("complete")
    (output / "run-manifest.json").write_text(
        canonical_json(
            {
                p.name: sha256_file(p)
                for p in output.iterdir()
                if p.is_file() and p.name != "run-manifest.json"
            }
        ),
        encoding="utf-8",
    )
    return {
        "run_id": report["run_id"],
        "included": prepared["included"],
        "topics": selected["topics"],
        "validation": forecast["validation"],
        "test": forecast["test"],
        "fidelity": forecast["fidelity"],
    }
