"""The audit must inspect code as data, without executing model/source payloads."""

import json

import pytest

from app.domain.common import AnalyticsError
from app.legacy import inspect_predictor, main


def source(tmp_path, code):
    path = tmp_path / "app/services"
    path.mkdir(parents=True)
    (path / "prediction_service.py").write_text(code, encoding="utf-8")
    return tmp_path


def test_extracts_contracts_without_executing_sources_or_models(tmp_path):
    root = source(
        tmp_path,
        """
raise RuntimeError("must never execute")
class Predictor:
    def _run_prediction(self):
        return Frame(columns=["year", "affiliation_encoded",
                              "publication_count", "distinct_authors"])
    def get_model_details(self):
        performance = {"mae": 2.2, "rmse": 4.67}
""",
    )
    (root / "publication_model.pkl").write_bytes(b"not a pickle")
    (root / "publication_data.csv").write_text("year,publication_count\n2020,1\n")
    report = inspect_predictor(root)
    assert report["source_declared_input_columns"][0] == "year"
    assert report["source_literal_metrics"]["mae"] == 2.2
    assert report["assets"]["affiliation_encoder.pkl"]["present"] is False
    assert report["historical_csv_columns"] == ["year", "publication_count"]
    assert report == inspect_predictor(root)


def test_nonliteral_metadata_remains_unknown(tmp_path):
    root = source(
        tmp_path,
        """
def _run_prediction():
    Frame(columns=some_expression())
def get_model_details():
    performance = compute_metrics()
""",
    )
    report = inspect_predictor(root)
    assert report["source_declared_input_columns"] is None
    assert report["source_literal_metrics"] is None


def test_missing_and_invalid_source_cli(tmp_path, capsys):
    with pytest.raises(AnalyticsError):
        inspect_predictor(tmp_path)
    assert main(["--repository", str(tmp_path)]) == 2
    assert json.loads(capsys.readouterr().err)["error"] == "predictor_source_missing"
    source(tmp_path, "pass")
    assert main(["--repository", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["execution"].startswith("no_import")
