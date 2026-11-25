"""Equivalent annual candidate comparisons with explicit prior test exposure."""

import math
from collections import defaultdict

from app.domain.annual_prediction import annual_rows, metrics
from app.domain.common import AnalyticsError, fingerprint


def error_breakdown(records):
    if not records:
        raise AnalyticsError("empty_evaluation", "Actual paired predictions required")
    groups = {"by_topic": defaultdict(list), "by_year": defaultdict(list)}
    cells = []
    for r in records:
        if r["observed"] is None:
            raise AnalyticsError("unobserved_target", "Do not score future targets")
        e = r["prediction"] - r["observed"]
        cells.append({**r, "signed_error": e, "absolute_error": abs(e)})
        groups["by_topic"][r["topic_id"]].append(r)
        groups["by_year"][str(r["year"])].append(r)
    result = {}
    for category, values in groups.items():
        result[category] = [
            {
                "key": key,
                **metrics(
                    [r["observed"] for r in rows], [r["prediction"] for r in rows]
                ),
                "bias": sum(r["prediction"] - r["observed"] for r in rows) / len(rows),
                "observed_total": sum(r["observed"] for r in rows),
                "predicted_total": sum(r["prediction"] for r in rows),
            }
            for key, rows in sorted(values.items())
        ]
    total = sum(r["absolute_error"] for r in cells)
    result["largest_errors"] = [
        {**r, "share_total_absolute_error": r["absolute_error"] / total if total else 0}
        for r in sorted(
            cells, key=lambda r: (-r["absolute_error"], r["topic_id"], r["year"])
        )
    ]
    result["interpretation"] = (
        "Descriptive error concentration; no causal attribution to events or coverage."
    )
    return result


def candidates():
    result = [{"id": v, "kind": v} for v in ("last_value", "mean3", "drift3")]
    for mode, scales, alphas, local in (
        ("log", False, [0.1, 1, 10, 100], False),
        ("log", True, [1, 10, 100], False),
        ("level", True, [1, 10, 100], False),
        ("log", True, [1, 10], True),
    ):
        for alpha in alphas:
            result.append(
                {
                    "id": (
                        f"ridge_{mode}_{'scaled' if scales else 'raw'}_"
                        f"{'per_topic' if local else 'pooled'}_{alpha}"
                    ),
                    "kind": "ridge",
                    "mode": mode,
                    "scaled": scales,
                    "alpha": alpha,
                    "per_topic": local,
                }
            )
    return result


def _inputs(row, mode):
    return (
        row["features"] if mode == "log" else [math.expm1(x) for x in row["features"]]
    )


def fit_candidate(rows, config):
    import numpy as np
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import StandardScaler

    if not rows or any(r["observed"] is None for r in rows):
        raise AnalyticsError("invalid_training", "Observed training rows required")
    content = {
        "config": config,
        "trained_through": max(r["year"] for r in rows),
        "training_sha256": fingerprint(rows),
        "training_rows": len(rows),
    }
    if config["kind"] == "ridge":
        x = np.asarray([_inputs(r, config["mode"]) for r in rows])
        y = np.asarray([r["observed"] for r in rows], dtype=float)
        if config["mode"] == "log":
            y = np.log1p(y)
        scaler = StandardScaler().fit(x) if config["scaled"] else None
        transformed = scaler.transform(x) if scaler is not None else x
        regressor = Ridge(alpha=config["alpha"], solver="svd").fit(transformed, y)
        scale = scaler.scale_ if scaler is not None else np.ones(x.shape[1])
        mean = scaler.mean_ if scaler is not None else np.zeros(x.shape[1])
        coefficient = regressor.coef_ / scale
        intercept = float(regressor.intercept_ - coefficient @ mean)
        assert np.allclose(x @ coefficient + intercept, regressor.predict(transformed))
        content.update(
            {
                "coefficients": coefficient.tolist(),
                "intercept": intercept,
                "scaler_mean": mean.tolist(),
                "scaler_scale": scale.tolist(),
                "input_and_output_scale": config["mode"],
            }
        )
    return {"model_id": fingerprint(content), **content}


def predict_candidate(model, row):
    content = {k: v for k, v in model.items() if k != "model_id"}
    if (
        fingerprint(content) != model["model_id"]
        or model["trained_through"] >= row["year"]
    ):
        raise AnalyticsError(
            "invalid_forecast_model", "Verified prior-year model required"
        )
    config = model["config"]
    past = [math.expm1(x) for x in row["features"][:3]]
    if config["kind"] == "last_value":
        value = row["last_value"]
    elif config["kind"] == "mean3":
        value = sum(past) / 3
    elif config["kind"] == "drift3":
        value = past[0] + (past[0] - past[2]) / 2
    else:
        value = model["intercept"] + math.fsum(
            c * x
            for c, x in zip(
                model["coefficients"], _inputs(row, config["mode"]), strict=True
            )
        )
        if config["mode"] == "log":
            if value > 30:
                raise AnalyticsError("unstable_forecast", "Extrapolation exceeds bound")
            value = math.expm1(value)
    if not math.isfinite(value):
        raise AnalyticsError("unstable_forecast", "Nonfinite forecast")
    return max(0.0, value)


def compare_annual(series, protocol):
    rows = [
        {"topic_id": topic, **row}
        for topic, points in sorted(series.items())
        for row in annual_rows(points)
    ]
    validation_years = list(
        range(protocol["topic_fit_end"] + 1, protocol["validation_end"] + 1)
    )
    diagnostic_years = list(
        range(protocol["validation_end"] + 1, protocol["test_end"] + 1)
    )
    models, experiments = {}, []
    for config in candidates():
        records = []
        for year in [*validation_years, *diagnostic_years]:
            targets = [r for r in rows if r["year"] == year]
            training = [
                r for r in rows if r["year"] < year and r["observed"] is not None
            ]
            by_group = {}
            for row in targets:
                group = row["topic_id"] if config.get("per_topic") else "pooled"
                if group not in by_group:
                    fit = (
                        [r for r in training if r["topic_id"] == group]
                        if group != "pooled"
                        else training
                    )
                    by_group[group] = fit_candidate(fit, config)
                    models[by_group[group]["model_id"]] = by_group[group]
                model = by_group[group]
                records.append(
                    {
                        "candidate_id": config["id"],
                        "topic_id": row["topic_id"],
                        "year": year,
                        "observed": row["observed"],
                        "prediction": predict_candidate(model, row),
                        "model_id": model["model_id"],
                        "trained_through": model["trained_through"],
                    }
                )
        partitions = {}
        for label, years in (
            ("validation", validation_years),
            ("previously_observed_diagnostic", diagnostic_years),
        ):
            subset = [r for r in records if r["year"] in years]
            partitions[label] = metrics(
                [r["observed"] for r in subset], [r["prediction"] for r in subset]
            )
        experiments.append({"config": config, **partitions, "records": records})
    winner = min(experiments, key=lambda e: (e["validation"]["mae"], e["config"]["id"]))
    nested = []
    for outer_year in validation_years[1:]:
        eligible = []
        for e in experiments:
            inner = [
                r
                for r in e["records"]
                if r["year"] in validation_years and r["year"] < outer_year
            ]
            score = metrics(
                [r["observed"] for r in inner], [r["prediction"] for r in inner]
            )
            eligible.append((score["mae"], e["config"]["id"], e))
        _, _, chosen = min(eligible, key=lambda t: (t[0], t[1]))
        outer = [r for r in chosen["records"] if r["year"] == outer_year]
        nested.append(
            {
                "outer_year": outer_year,
                "selection_years": [y for y in validation_years if y < outer_year],
                "candidate_id": chosen["config"]["id"],
                **metrics(
                    [r["observed"] for r in outer], [r["prediction"] for r in outer]
                ),
            }
        )
    winner_records = winner["records"]
    forecast = []
    for row in (r for r in rows if r["observed"] is None):
        fit = [r for r in rows if r["observed"] is not None]
        if winner["config"].get("per_topic"):
            fit = [r for r in fit if r["topic_id"] == row["topic_id"]]
        model = fit_candidate(fit, winner["config"])
        models[model["model_id"]] = model
        forecast.append(
            {
                "topic_id": row["topic_id"],
                "year": row["year"],
                "prediction": predict_candidate(model, row),
                "model_id": model["model_id"],
            }
        )
    return {
        "candidate_count": len(experiments),
        "selected_by_development": winner["config"]["id"],
        "selection_uses_only_years": validation_years,
        "nested_development": nested,
        "test_exposure": (
            "2019-2021 previously observed; exploratory diagnostic, not u"
            "ntouched confirmation"
        ),
        "candidates": experiments,
        "selected_diagnostics": error_breakdown(
            [r for r in winner_records if r["year"] in diagnostic_years]
        ),
        "projection_after_last_cutoff": forecast,
        "deployment_status": (
            "not_promoted; new-model XAI must use its own model contract"
        ),
    }, models
