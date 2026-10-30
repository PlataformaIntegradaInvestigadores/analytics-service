"""Paired reference comparison on common temporal origins, excluding final test."""

import math

from app.domain.common import fingerprint
from app.domain.forecasting import backtest


def compare_references(points: list[dict], **options) -> dict:
    evaluations = {
        method: backtest(points, method=method, **options)
        for method in ("last_value", "seasonal_naive")
    }
    indexed = {
        method: {fold["cutoff"]: fold for fold in evaluation["folds"]}
        for method, evaluation in evaluations.items()
    }
    common = sorted(set(indexed["last_value"]) & set(indexed["seasonal_naive"]))
    summary = {}
    for method, folds in indexed.items():
        paired = [folds[cutoff] for cutoff in common]
        actual = [value for fold in paired for value in fold["observed"]]
        predicted = [
            point["value"]
            for fold in paired
            for point in fold["forecast"]["predictions"]
        ]
        errors = [abs(a - p) for a, p in zip(actual, predicted, strict=True)]
        volume = math.fsum(actual)
        scaled = [fold["metrics"]["mase_lag1"] for fold in paired]
        summary[method] = {
            "n": len(actual),
            "mae": math.fsum(errors) / len(errors) if errors else None,
            "rmse": (
                math.sqrt(math.fsum(error**2 for error in errors) / len(errors))
                if errors
                else None
            ),
            "wape": math.fsum(errors) / volume if volume else None,
            "mean_fold_mase_lag1": (
                math.fsum(scaled) / len(scaled)
                if scaled and all(value is not None for value in scaled)
                else None
            ),
        }
    preferred = None
    if common:
        left, right = (
            summary[method]["mae"] for method in ("last_value", "seasonal_naive")
        )
        preferred = (
            "tie"
            if left == right
            else "last_value" if left < right else "seasonal_naive"
        )
    # All identities below depend on development observations only.
    content = {
        "comparison_algorithm": "paired-reference-comparison-v1",
        "configuration": options,
        "development_sha256": evaluations["last_value"]["development_sha256"],
        "status": "ok" if common else "insufficient_data",
        "common_origins": common,
        "paired_folds": [
            {
                "cutoff": cutoff,
                "observed": indexed["last_value"][cutoff]["observed"],
                "predictions": {
                    method: folds[cutoff]["forecast"]["predictions"]
                    for method, folds in indexed.items()
                },
            }
            for cutoff in common
        ],
        "metrics": summary,
        "preferred_by_validation_mae": preferred,
        "omitted": {
            method: {
                "skipped": evaluations[method]["skipped"],
                "unpaired_origins": sorted(set(folds) - set(common)),
            }
            for method, folds in indexed.items()
        },
        "test_policy": (
            "Final test excluded; overlapping horizons count as separate "
            "origin-target pairs; no trained model selected"
        ),
    }
    return {"comparison_id": fingerprint(content), **content}
