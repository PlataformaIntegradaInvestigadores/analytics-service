"""Boundary fixtures and causal-order checks; never research result fabrication."""

import csv
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.data.research_audit import audit_snapshot
from app.data.research_corpus import SCHEMAS, ingest_research
from app.domain.common import AnalyticsError, fingerprint
from app.domain.forecast_review import (
    candidates,
    compare_annual,
    error_breakdown,
    fit_candidate,
    predict_candidate,
)
from app.main import create_app
from app.review import trace_contract
from app.topic_review import (
    clean_markup,
    fit_lda,
    infer_lda,
    stability,
    summarize_model,
)


def test_markup_cleanup_preserves_scientific_content():
    assert clean_markup("A<inf>2</inf> &amp; B") == "A 2 & B"
    assert clean_markup("p < 0.05 and x > 3") == "p < 0.05 and x > 3"
    assert clean_markup("A&lt;sub&gt;2&lt;/sub&gt;") == "A 2"


def points():
    return {
        "a": [{"year": y, "count": (y - 1998) ** 2} for y in range(2000, 2022)],
        "b": [{"year": y, "count": (y - 1998) * 3} for y in range(2000, 2022)],
    }


def test_exposed_test_cannot_select_parameters_and_every_cut_is_prior():
    protocol = {"topic_fit_end": 2015, "validation_end": 2018, "test_end": 2021}
    result, models = compare_annual(points(), protocol)
    altered = points()
    for rows in altered.values():
        rows[-1]["count"] = 999999
    changed, _ = compare_annual(altered, protocol)
    assert result["selected_by_development"] == changed["selected_by_development"]
    assert result["nested_development"] == changed["nested_development"]
    for left, right in zip(result["candidates"], changed["candidates"], strict=True):
        assert left["validation"] == right["validation"]
        assert all(r["trained_through"] < r["year"] for r in left["records"])
    for entry in result["nested_development"]:
        assert max(entry["selection_years"]) < entry["outer_year"]
    assert len(result["candidates"]) == 15
    assert models and len(result["projection_after_last_cutoff"]) == 2
    assert "not untouched" in result["test_exposure"]


def test_errors_reconcile_and_keep_sign():
    values = [
        {"topic_id": "a", "year": 2020, "observed": 10, "prediction": 14},
        {"topic_id": "a", "year": 2021, "observed": 10, "prediction": 8},
    ]
    result = error_breakdown(values)
    assert result["by_topic"][0]["mae"] == 3
    assert result["by_topic"][0]["bias"] == 1
    assert sum(r["share_total_absolute_error"] for r in result["largest_errors"]) == 1
    with pytest.raises(AnalyticsError):
        error_breakdown([])
    with pytest.raises(AnalyticsError):
        error_breakdown([{**values[0], "observed": None}])
    with pytest.raises(AnalyticsError):
        fit_candidate([], candidates()[0])
    rows = [{"features": [1, 2, 3, 2], "year": 2020, "observed": 4, "last_value": 3}]
    m = fit_candidate(rows, candidates()[0])
    with pytest.raises(AnalyticsError):
        predict_candidate(m, rows[0])
    with pytest.raises(AnalyticsError):
        predict_candidate({**m, "trained_through": 1999}, {**rows[0], "year": 2021})


def test_lda_json_reconstruction_and_oov_policy():
    docs = [
        {"document_id": str(i), "publication_date": "2010-01-01", "text": t}
        for i, t in enumerate(
            [
                "neural networks learning graph models",
                "graph algorithms neural learning networks",
                "machine learning neural graph algorithms",
                "tropical forest habitat species conservation",
                "biodiversity forest species tropical habitat",
                "species forest biodiversity ecology conservation",
            ]
        )
    ]
    template = {
        "configuration": {"vectorizer": {"min_df": 1, "max_df": 0.99}},
        "versions": {},
        "research_protocol": {},
    }
    model = fit_lda(docs, template, components=2)
    weights, valid = infer_lda(
        model, docs + [{"document_id": "unknown", "text": "zzzzzz"}]
    )
    assert weights.shape == (7, 2) and not valid[-1]
    summary, _, _ = summarize_model(model, docs)
    assert summary["coverage"] == 1 and len(summary["topics"]) == 2
    with pytest.raises(AnalyticsError):
        infer_lda({**model, "doc_topic_prior": 999}, docs)
    a = {
        "vocabulary": {"a": 0, "b": 1},
        "components": [[1, 0], [0, 1]],
        "configuration": {"seed": 43},
        "model_id": "x",
    }
    b = {**a, "components": [[0, 1], [1, 0]]}
    assert stability(a, [b])["results"][0]["mean_matched_cosine"] == 1
    with pytest.raises(AnalyticsError):
        stability(a, [{**b, "vocabulary": {}}])


def test_readonly_corpus_audit_and_pending_owner_decisions(tmp_path):
    source = tmp_path / "raw"
    source.mkdir()
    data = {name: [] for name in SCHEMAS}
    data.update(
        {
            "articles": [
                [
                    "1",
                    "One",
                    "2020-01-01",
                    "10.9999/same",
                    "Text summary",
                    "9",
                    "1",
                    "False",
                ],
                [
                    "2",
                    "Two",
                    "2021-01-01",
                    "10.9999/same",
                    "Other summary",
                    "1",
                    "1",
                    "True",
                ],
            ],
            "authors": [["u", "", "", "Name", ""]],
            "affiliations": [["af", "Org", "", ""]],
            "author_keywords": [["kw", "word"]],
            "articles_authors": [["1", "u"], ["1", "u"], ["absent", "u"]],
            "articles_affiliations": [["1", "af"]],
            "articles_author_keywords": [["1", "kw", "word"]],
            "authors_affiliations": [["u", "af"]],
        }
    )
    for name, columns in SCHEMAS.items():
        with (source / (name + ".csv")).open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(columns)
            writer.writerows(data[name])
    corpus = tmp_path / "source.sqlite"
    ingest_research(source, corpus, approval_reference="Unit contract only")
    prepared = tmp_path / "prepared.sqlite"
    with sqlite3.connect(prepared) as db:
        db.execute(
            "CREATE TABLE prepared(article_id TEXT,year INTEGER,document_id TEXT)"
        )
        db.execute("CREATE TABLE assignments(document_id TEXT,topic_id TEXT)")
        db.executemany(
            "INSERT INTO prepared VALUES (?,?,?)",
            [("1", 2020, "d1"), ("2", 2021, "d2")],
        )
        db.executemany(
            "INSERT INTO assignments VALUES (?,?)", [("d1", "a"), ("d2", "b")]
        )
    before = corpus.read_bytes()
    summary, private = audit_snapshot(corpus, prepared)
    assert corpus.read_bytes() == before
    assert summary["doi_cross_year_groups"] == 1
    assert summary["quarantine_sensitivity"]["affected_prepared_documents"] == 2
    assert summary["relationships"]["articles_authors"]["orphan_rows"] == 1
    assert summary["relationships"]["articles_authors"]["repeated_valid_pairs"] == 1
    assert not summary["owner_decisions_applied"]
    assert private["doi_cases"][0]["decision"] is None
    assert private["doi_cases"][0]["records"][0]["raw_record"] == 2


def test_remote_contract_identity_hierarchy_and_review_integrity(tmp_path):
    from app.review import REQUIREMENTS

    plan = tmp_path / "plan.pdf"
    plan.write_bytes(b"unit plan fingerprint fixture")
    backlog = {"items": [{"code": "F", "remote_id": 1, "type": "Feature"}]}
    items = []
    for i, code in enumerate(REQUIREMENTS, 2):
        backlog["items"].append(
            {"code": code, "remote_id": i, "type": "Requirement", "parent": "F"}
        )
        items.append(
            {
                "id": i,
                "rev": 4,
                "fields": {
                    "System.Title": "[" + code + "] fixture",
                    "System.TeamProject": "Centinela-Analitica-Jairo",
                    "System.WorkItemType": "Requirement",
                    "System.State": "Active",
                },
                "relations": [
                    {
                        "rel": "System.LinkTypes.Hierarchy-Reverse",
                        "url": "https://example.test/1",
                    }
                ],
            }
        )
    snap = {
        "organization": "centinela-jairo-quispe",
        "project": "Centinela-Analitica-Jairo",
        "process": "CMMI",
        "items": items,
    }
    assert len(trace_contract(snap, backlog, plan)["items"]) == 9
    with pytest.raises(AnalyticsError):
        trace_contract({**snap, "process": "Agile"}, backlog, plan)
    items[0]["relations"] = []
    with pytest.raises(AnalyticsError):
        trace_contract(snap, backlog, plan)
    path = tmp_path / "review.sqlite"
    content = {
        "run_id": "fixture",
        "identity": {"private": "omitted"},
        "status": "fixture",
    }
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE review(id TEXT,payload TEXT)")
        db.execute(
            "INSERT INTO review VALUES (?,?)",
            ("fixture", json.dumps({**content, "report_sha256": fingerprint(content)})),
        )
    with TestClient(create_app(Settings(review_database=path))) as c:
        value = c.get("/api/v1/study/review")
        assert value.status_code == 200 and "identity" not in value.json()
    with TestClient(
        create_app(Settings(environment="production", review_database=path))
    ) as c:
        assert c.get("/api/v1/study/review").status_code == 503
    with TestClient(create_app(Settings())) as c:
        assert c.get("/api/v1/study/review").status_code == 503


def test_review_api_rejects_empty_or_tampered_store(tmp_path):
    path = tmp_path / "review.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE review(id TEXT,payload TEXT)")
    with TestClient(create_app(Settings(review_database=path))) as client:
        assert client.get("/api/v1/study/review").json()["detail"]["code"] == (
            "review_missing"
        )
        with sqlite3.connect(path) as db:
            db.execute(
                "INSERT INTO review VALUES (?,?)",
                ("fixture", '{"run_id":"tampered","report_sha256":"incorrect"}'),
            )
        response = client.get("/api/v1/study/review")
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "review_integrity"


def test_cli_refuses_undeclared_test_exposure_before_writing(tmp_path, capsys):
    from app.review import main

    protocol = tmp_path / "protocol.json"
    protocol.write_text("{}", encoding="utf8")
    output = tmp_path / "must-not-exist"
    args = []
    for name in (
        "corpus",
        "study-directory",
        "source-directory",
        "plan",
        "azure-snapshot",
        "backlog",
        "protocol",
        "output",
    ):
        value = protocol if name == "protocol" else output
        args.extend(["--" + name, str(value)])
    assert main(args) == 2
    assert "test_exposure_required" in capsys.readouterr().err
    assert not output.exists()
    protocol.write_text(
        json.dumps(
            {
                "prior_test_exposure": "previously_observed_exploratory_only",
                "forecast_candidates": [],
            }
        ),
        encoding="utf8",
    )
    assert main(args) == 2
    assert "protocol_candidate_mismatch" in capsys.readouterr().err
    assert not output.exists()
