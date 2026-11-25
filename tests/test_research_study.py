"""Small contract fixtures are unit tests, never empirical thesis evidence."""

import json
import math
import sqlite3

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.study import read_study
from app.core.config import Settings
from app.domain.annual_prediction import (
    annual_rows,
    explain_prediction,
    metrics,
    train_ridge,
)
from app.domain.common import AnalyticsError
from app.domain.forecast_evidence import forecast_comparison
from app.main import create_app
from app.research_execution import forecast_study, run_study
from app.schemas.study import StudyProtocol


def config():
    return {
        "start_year": 2000,
        "topic_fit_end": 2008,
        "validation_end": 2010,
        "test_end": 2012,
        "topic_candidates": [2],
        "ridge_alphas": [1.0, 10.0],
        "min_df": 1,
        "max_features": 100,
        "approval_reference": "Unit test contract only",
        "rationale": "Unit fixture for temporal boundaries; not a research result",
    }


def test_annual_features_do_not_see_target_or_future():
    points = [{"year": 2000 + i, "count": i + 3} for i in range(14)]
    rows = annual_rows(points)
    changed = annual_rows([*points[:-1], {"year": 2013, "count": 999999}])
    assert rows[-2]["features"] == changed[-2]["features"]
    assert rows[-2]["observed"] != changed[-2]["observed"]
    model = train_ridge(rows[:7], 1.0)
    prediction = explain_prediction(model, rows[-2])
    e = prediction["explanation"]
    assert e["additivity_residual"] < 1e-12
    assert e["base_value"] + sum(e["contributions"]) == pytest.approx(e["output_value"])
    assert prediction["prediction"] == pytest.approx(
        max(0, math.expm1(e["output_value"]))
    )
    assert (
        explain_prediction(model, changed[-2])["prediction"] == prediction["prediction"]
    )
    with pytest.raises(AnalyticsError):
        explain_prediction(model, rows[0])
    with pytest.raises(AnalyticsError):
        explain_prediction({**model, "intercept": 999}, rows[-2])


@pytest.mark.parametrize(
    "points",
    [
        [],
        [{"year": 2000 + i, "count": -1} for i in range(4)],
        [{"year": 2000 + i * 2, "count": 1} for i in range(4)],
        [{"year": True, "count": 1} for _ in range(4)],
    ],
)
def test_invalid_annual_series(points):
    with pytest.raises(AnalyticsError):
        annual_rows(points)


def test_validation_selection_excludes_reserved_test_targets():
    p = StudyProtocol.model_validate(config())
    points = [{"year": y, "count": (y - 1998) ** 2} for y in range(2000, 2013)]
    a, _ = forecast_study({"topic-0": points}, p)
    altered = [{**r, "count": 9999} if r["year"] == 2012 else r for r in points]
    b, _ = forecast_study({"topic-0": altered}, p)
    assert a["selected_alpha"] == b["selected_alpha"]
    assert a["validation_candidates"] == b["validation_candidates"]
    assert a["test_records"][0]["prediction"] == b["test_records"][0]["prediction"]
    assert a["fidelity"]["value"] < 1e-12
    assert a["test"]["ridge"]["n"] == 2
    paired = forecast_comparison({"topic-0": points}, p.model_dump(), a)
    assert paired["validation"]["overall"]["ridge"] == a["validation"]["ridge"]
    assert (
        paired["diagnostic"]["by_topic"]["topic-0"]["last_value"]
        == a["test"]["last_value"]
    )
    assert paired["diagnostic"]["by_year"]["2012"]["ridge"]["n"] == 1
    assert paired["last_observed_year"] == 2012
    assert paired["diagnostic_scope"] == "previously_observed_exploratory"
    for bad_records in (
        a["test_records"][:-1],
        [{**row, "baseline_last_value": -1} for row in a["test_records"]],
        [*a["test_records"], a["test_records"][0]],
    ):
        with pytest.raises(AnalyticsError, match="forecast|Forecast"):
            forecast_comparison(
                {"topic-0": points}, p.model_dump(), {**a, "test_records": bad_records}
            )


@pytest.mark.parametrize(
    "override",
    [
        {"topic_fit_end": 2000},
        {"validation_end": 2013},
        {"topic_candidates": [True]},
        {"ridge_alphas": [float("nan")]},
        {"ridge_alphas": [1, 1]},
    ],
)
def test_invalid_protocol(override):
    with pytest.raises(ValidationError):
        StudyProtocol.model_validate(config() | override)


def test_metrics_invalid():
    with pytest.raises(AnalyticsError):
        metrics([], [])
    with pytest.raises(AnalyticsError):
        metrics([1], [float("nan")])
    with pytest.raises(AnalyticsError):
        train_ridge([], 1)


def test_complete_fixture_run_integrity_and_local_guard(tmp_path):
    corpus = tmp_path / "source.sqlite"
    with sqlite3.connect(corpus) as db:
        db.execute(
            "CREATE TABLE articles(article_id TEXT,year TEXT,"
            "publication_date TEXT,document TEXT)"
        )
        for year in range(2000, 2013):
            for index, text in enumerate(
                [
                    "neural algorithms graph learning networks models",
                    "ecology species forest habitat biodiversity conservation",
                ]
            ):
                doc = {
                    "document_id": f"unit-{year}-{index}",
                    "title": text + f" census {year}",
                    "abstract": text + " evidence study measurement",
                    "publication_date": f"{year}-01-01",
                }
                db.execute(
                    "INSERT INTO articles VALUES (?,?,?,?)",
                    (
                        doc["document_id"],
                        str(year),
                        doc["publication_date"],
                        json.dumps(doc),
                    ),
                )
        db.execute("CREATE TABLE manifest(payload TEXT)")
        db.execute(
            "INSERT INTO manifest VALUES (?)",
            (
                json.dumps(
                    {
                        "use_scope": "research_authorized_as_declared",
                        "source_version": "f" * 64,
                        "articles": 26,
                    }
                ),
            ),
        )
    before = corpus.read_bytes()
    output = tmp_path / "study"
    result = run_study(corpus, output, config())
    report = read_study(output / "study.sqlite")
    assert result["included"] == 26 and report["data_kind"] == "empirical"
    assert "identity" not in report and "approval_reference" not in report["protocol"]
    assert all("representative_article_ids" not in t for t in report["topics"])
    assert report["prediction"]["test"]["ridge"]["n"] == 4
    with sqlite3.connect(output / "models.sqlite") as db:
        payload = json.loads(
            db.execute("SELECT payload FROM fitted_models").fetchone()[0]
        )
        assert payload["purpose"] == "research"
        assert all(int(d.split("-")[1]) <= 2008 for d in payload["fit_ids"])
    assert corpus.read_bytes() == before
    with pytest.raises(AnalyticsError):
        run_study(corpus, output, config())
    with TestClient(create_app(Settings(study_database=output / "study.sqlite"))) as c:
        response = c.get("/api/v1/study")
        assert response.status_code == 200
        assert (
            response.json()["forecast_comparison"]["diagnostic"]["overall"]["ridge"][
                "n"
            ]
            == 4
        )
        assert (
            c.get("/api/v1/study", params={"release_id": "f" * 64}).status_code == 503
        )
    with TestClient(
        create_app(
            Settings(environment="production", study_database=output / "study.sqlite")
        )
    ) as c:
        assert c.get("/api/v1/study").status_code == 503
    with TestClient(create_app(Settings())) as c:
        assert c.get("/api/v1/study").status_code == 503
    with sqlite3.connect(output / "study.sqlite") as db:
        db.execute("UPDATE study SET payload='{}'")
    with pytest.raises(AnalyticsError):
        read_study(output / "study.sqlite")


def test_research_requires_protocol():
    from app.application.modeling import fit_nmf

    with pytest.raises(AnalyticsError) as e:
        fit_nmf([], [], workset_id="f" * 64, purpose="research")
    assert e.value.code == "invalid_research_protocol"
