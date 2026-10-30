import importlib.metadata
import json
import sqlite3
from unittest.mock import patch

import pytest

from app.application.modeling import (
    bertopic_capability,
    fit_bertopic,
    fit_nmf,
    infer_nmf,
    validate_documents,
)
from app.core.provenance import source_files
from app.data.models import ModelStore
from app.data.versioned_tables import VersionedTable
from app.domain.common import AnalyticsError
from app.domain.explainability import explanation_contract
from app.domain.temporal import aggregate, next_period, period
from app.modeling import main as modeling_main
from app.reproduce import main as reproduce_main


@pytest.fixture
def docs():
    return [
        {
            "document_id": str(i),
            "text": text,
            "publication_date": "2020-01-01",
            "available_on": "2020-02-01",
        }
        for i, text in enumerate(
            [
                "solar panel sunlight energy",
                "renewable solar energy panel",
                "neural learning machine model",
                "machine neural model training",
            ]
        )
    ]


@pytest.fixture
def model(docs):
    return fit_nmf(
        docs, ["0", "1", "2", "3"], workset_id="a" * 64, software=source_files()
    )


def test_roundtrip_inference_and_heldout_vocabulary(docs, model, tmp_path):
    store = ModelStore(tmp_path / "models.sqlite")
    assert store.save(model) == model == store.save(model)
    assert infer_nmf(model, docs) == infer_nmf(store.load(model["model_id"]), docs)
    assert (
        infer_nmf(model, [{"document_id": "new", "text": "zzzzzz"}])[0]["topic_id"]
        is None
    )
    again = fit_nmf(
        list(reversed(docs)),
        ["3", "2", "1", "0"],
        workset_id="a" * 64,
        software=source_files(),
    )
    assert again["model_id"] == model["model_id"]
    fit = fit_nmf(docs, ["0", "1"], workset_id="a" * 64, cutoff="2020-02-01")
    assert "neural" not in fit["vocabulary"]
    assert fit["temporal_status"] == "verified_declared_availability"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"purpose": "research"},
        {"topics": 1},
        {"topics": 8},
        {"seed": -1},
        {"seed": True},
        {"max_iter": 1},
        {"max_features": 2},
        {"workset_id": "x" * 64},
        {"workset_id": "a"},
    ],
)
def test_invalid_config(docs, kwargs):
    with pytest.raises(AnalyticsError):
        fit_nmf(docs, ["0", "1"], **{"workset_id": "a" * 64, **kwargs})


@pytest.mark.parametrize(
    "change", ["duplicate", "blank", "ids", "empty", "missing", "future"]
)
def test_invalid_documents(docs, change):
    ids = ["0", "1"]
    if change == "duplicate":
        docs.append(docs[0])
    elif change == "blank":
        docs[0]["text"] = " "
    elif change == "ids":
        ids = ["absent"]
    elif change == "empty":
        ids = []
    elif change == "missing":
        docs[0]["available_on"] = None
    else:
        docs[0]["publication_date"] = "2022-01-01"
    with pytest.raises(AnalyticsError):
        validate_documents(docs, ids, "2021-01-01")


def test_empty_and_insufficient_vocabulary(docs):
    for doc in docs:
        doc["text"] = "a"
    with pytest.raises(AnalyticsError, match="vocabulary"):
        fit_nmf(docs, ["0", "1"], workset_id="a" * 64)
    for doc in docs:
        doc["text"] = "one"
    with pytest.raises(AnalyticsError, match="terms"):
        fit_nmf(docs, ["0", "1"], workset_id="a" * 64)


def test_model_corruption(docs, model, tmp_path):
    store = ModelStore(tmp_path / "models.sqlite")
    for identifier in ("a", "a" * 64):
        with pytest.raises(AnalyticsError):
            store.load(identifier)
    with pytest.raises(AnalyticsError):
        store.save({**model, "purpose": "research"})
    store.save(model)
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE fitted_models SET payload='{}'")
    with pytest.raises(AnalyticsError):
        store.load(model["model_id"])
    with pytest.raises(AnalyticsError):
        infer_nmf({**model, "idf": [1]}, docs)
    for invalid in ([], [docs[0], docs[0]], [{"document_id": "x", "text": ""}]):
        with pytest.raises(AnalyticsError):
            infer_nmf(model, invalid)


def test_bertopic_validation_and_capability(docs):
    with patch(
        "importlib.metadata.version",
        side_effect=importlib.metadata.PackageNotFoundError,
    ):
        assert not bertopic_capability()["available"]
    with patch(
        "app.application.modeling.bertopic_capability",
        return_value={"available": False},
    ):
        with pytest.raises(AnalyticsError, match="absent"):
            fit_bertopic(docs, ["0", "1"], [[1, 2], [2, 3]])
    for embedding in ([], [[1]], [[float("nan")], [2]], [[1], [1, 2]]):
        with pytest.raises(AnalyticsError, match="finite"):
            fit_bertopic(docs, ["0", "1"], embedding)


@pytest.mark.parametrize(
    "granularity,value,expected",
    [
        ("year", "2020", "2021"),
        ("quarter", "2020-Q4", "2021-Q1"),
        ("quarter", "2020-Q1", "2020-Q2"),
        ("month", "2020-12", "2021-01"),
        ("month", "2020-01", "2020-02"),
    ],
)
def test_period_success(granularity, value, expected):
    assert next_period(value, granularity) == expected


@pytest.mark.parametrize(
    "granularity,value",
    [
        ("month", "2020-13"),
        ("day", "2020"),
        ("year", "9999"),
        ("quarter", "2020-Q0"),
        ("year", "0000"),
    ],
)
def test_period_reject(granularity, value):
    with pytest.raises(AnalyticsError):
        next_period(value, granularity)


def test_temporal_guard(docs):
    assert period("2020-11-01", "quarter", "day") == "2020-Q4"
    for precision, granularity in [("unknown", "year"), ("year", "month")]:
        with pytest.raises(AnalyticsError):
            period("2020-01-01", granularity, precision)
    result = aggregate(
        docs,
        {"0": "solar"},
        granularity="year",
        precision="year",
        complete_periods=["2021"],
    )
    assert result[0]["coverage"] == "unknown"
    assert result[1]["observed_documents"] == 0
    assert result[0]["topics"] == {"solar": 1}
    with pytest.raises(AnalyticsError):
        aggregate(docs, {"unknown": "topic"}, granularity="year", precision="year")


def test_table_transactions_history_schema_integrity(tmp_path):
    table = VersionedTable(tmp_path)
    first = table.commit([{"id": 1}])
    with pytest.raises(AnalyticsError, match="Head"):
        table.commit([{"id": 2}])
    with pytest.raises(AnalyticsError, match="additive"):
        table.commit([{"id": "wrong_type"}], expected_parent=first)
    second = table.commit([{"id": 2, "extra": True}], expected_parent=first)
    assert table.read(first) == [{"id": 1}]
    assert table.read(second, ["id"]) == [{"id": 2}]
    for rows in ([], [{"a": 1}, {"b": 2}], [None]):
        with pytest.raises(AnalyticsError):
            table.commit(rows, expected_parent=second)
    for identifier in ("bad", "f" * 64):
        with pytest.raises(AnalyticsError):
            table.read(identifier)
    with pytest.raises(AnalyticsError):
        table.read(first, ["nope"])
    (tmp_path / f"{first}.parquet").write_bytes(b"corrupt")
    with pytest.raises(AnalyticsError):
        table.read(first)


def test_explainer_boundary():
    valid = dict(
        model_id="linear-fixture",
        features=["lag"],
        row=[1.0],
        prediction=2,
        target="documents",
        training_features=["lag"],
        method="linear_exact",
        model_family="linear",
    )
    assert explanation_contract(**valid)["status"] == "compatible_not_explained"
    for change in (
        {"features": ["other"]},
        {"row": [float("nan")]},
        {"row": [True]},
        {"method": "tree_shap"},
        {"model_id": ""},
    ):
        with pytest.raises(AnalyticsError):
            explanation_contract(**{**valid, **change})


def test_cli_reproduction_and_models(tmp_path, docs, model, capsys):
    out = tmp_path / "evidence"
    assert reproduce_main(["--output", str(out)]) == 0
    assert json.loads((out / "report.json").read_text())["empirical_training"] is False
    with pytest.raises(SystemExit):
        reproduce_main(["--output", str(out)])
    database = str(tmp_path / "model.sqlite")
    request = tmp_path / "input.json"
    request.write_text(
        json.dumps(
            {"documents": docs, "fit_ids": ["0", "1", "2", "3"], "workset_id": "a" * 64}
        )
    )
    assert modeling_main(["fit", "--database", database, "--input", str(request)]) == 0
    assert modeling_main(["capabilities"]) == 0
    assert (
        modeling_main(["show", "--database", database, "--id", model["model_id"]]) == 0
    )
    request.write_text(json.dumps(docs))
    assert (
        modeling_main(
            [
                "infer",
                "--database",
                database,
                "--id",
                model["model_id"],
                "--input",
                str(request),
            ]
        )
        == 0
    )
    request.write_text("{}")
    assert modeling_main(["fit", "--database", database, "--input", str(request)]) == 2
    assert capsys.readouterr().out
