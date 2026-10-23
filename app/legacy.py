"""Static predictive-service inspection: never imports code or unpickles assets."""

import argparse
import ast
import csv
import sys
from pathlib import Path

from app.core.provenance import sha256_file
from app.domain.common import AnalyticsError, canonical_json, fingerprint


def inspect_predictor(root: Path) -> dict:
    root = root.resolve()
    names = (
        "app/services/prediction_service.py",
        "preprocess_data.py",
        "publication_model.pkl",
        "affiliation_encoder.pkl",
        "publication_data.csv",
    )
    assets = {}
    for name in names:
        path = (root / name).resolve()
        if not path.is_relative_to(root):
            raise AnalyticsError("unsafe_predictor_path", "Asset leaves the repository")
        assets[name] = {
            "present": path.is_file(),
            "sha256": sha256_file(path) if path.is_file() else None,
        }
    service = root / names[0]
    if not service.is_file():
        raise AnalyticsError(
            "predictor_source_missing", "Prediction service source absent"
        )
    tree = ast.parse(service.read_text(encoding="utf-8-sig"))
    features, declared_metrics = None, None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_run_prediction":
            for call in ast.walk(node):
                if isinstance(call, ast.Call):
                    for keyword in call.keywords:
                        if keyword.arg == "columns":
                            try:
                                features = ast.literal_eval(keyword.value)
                            except (ValueError, TypeError):
                                pass
        if isinstance(node, ast.FunctionDef) and node.name == "get_model_details":
            for assignment in ast.walk(node):
                if isinstance(assignment, ast.Assign) and any(
                    isinstance(target, ast.Name) and target.id == "performance"
                    for target in assignment.targets
                ):
                    try:
                        declared_metrics = ast.literal_eval(assignment.value)
                    except (ValueError, TypeError):
                        pass
    header = None
    if assets["publication_data.csv"]["present"]:
        with (root / "publication_data.csv").open(
            encoding="utf-8-sig", newline=""
        ) as stream:
            header = next(csv.reader(stream), [])
    result = {
        "audit_version": "predictive-source-inspection-v1",
        "assets": assets,
        "source_declared_input_columns": features,
        "historical_csv_columns": header,
        "source_literal_metrics": declared_metrics,
        "metrics_verification": "unverified_source_constants_not_executed_evaluation",
        "task_compatibility": (
            "affiliation_publication_projection_not_thematic_forecasting"
        ),
        "execution": "no_import_no_unpickle_no_inference_no_training",
        "reuse_candidates": [
            "HTTP projection contracts",
            "observed/projected separation",
        ],
        "pending": [
            "training evidence",
            "holdout evaluation",
            "artifact runtime compatibility",
            "temporal input semantics",
        ],
    }
    return {"audit_id": fingerprint(result), **result}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        print(canonical_json(inspect_predictor(args.repository)))
        return 0
    except (AnalyticsError, OSError, SyntaxError, UnicodeError) as exc:
        print(
            canonical_json(
                {
                    "error": getattr(exc, "code", "invalid_predictor_source"),
                    "message": str(exc),
                }
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
