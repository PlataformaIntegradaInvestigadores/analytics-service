"""Observed/forecast and pending-XAI projections of already saved results."""

from app.application.analysis import aggregate_batch
from app.domain.common import AnalyticsError, fingerprint, parse_month


def explanation_state(artifact: dict, scope: str = "local") -> dict:
    if artifact["kind"] != "reference_forecast":
        raise AnalyticsError(
            "incompatible_artifact", "Select a saved reference forecast"
        )
    if scope not in ("local", "global"):
        raise AnalyticsError("invalid_explanation_scope", "Use local or global scope")
    result = artifact["result"]
    available = result["status"] == "ok"
    return {
        "experiment_id": artifact["experiment_id"],
        "status": "pending" if available else "unavailable",
        "scope": scope,
        "reason": (
            "explainer_not_implemented" if available else "forecast_insufficient_data"
        ),
        "model_version": result["model_version"],
        "inputs_sha256": fingerprint(artifact["request"]),
        "predictions_sha256": fingerprint(result["predictions"]),
        "method": None,
        "attributions": [],
    }


def dashboard_contract() -> dict:
    return {
        "contract_version": "analytics-dashboard-v1",
        "unit": "documents",
        "granularity": "calendar_month",
        "filters": ["topic_id", "data_kind", "kind", "status", "start", "end"],
        "display_states": ["loading", "ready", "empty", "error", "insufficient_data"],
        "observed_forecast_policy": (
            "Observed through cutoff only; future forecast is a separate series; "
            "no confidence interval is estimated"
        ),
        "null_policy": (
            "Unknown coverage stays null; zero requires declared complete coverage"
        ),
        "xai_policy": (
            "Display pending or unavailable until an explanation actually exists"
        ),
    }


def dashboard_view(
    artifact: dict, start: str | None = None, end: str | None = None
) -> dict:
    explanation = explanation_state(artifact)
    for period in (start, end):
        if period is not None:
            parse_month(period)
    if start and end and start > end:
        raise AnalyticsError("invalid_window", "Start must not exceed end")
    request, result = artifact["request"], artifact["result"]
    series = aggregate_batch(request["series"])
    if any(
        result[key] != series[key]
        for key in (
            "dataset_version",
            "series_version",
            "topic_definition_version",
            "data_kind",
        )
    ):
        raise AnalyticsError(
            "experiment_provenance_mismatch",
            "Current series construction differs from the saved result",
        )

    def in_window(period):
        return (start is None or period >= start) and (end is None or period <= end)

    observed = [
        point
        for point in series["points"]
        if point["topic_id"] == result["topic_id"]
        and point["period"] <= result["cutoff"]
        and in_window(point["period"])
    ]
    predicted = [point for point in result["predictions"] if in_window(point["period"])]
    return {
        "experiment_id": artifact["experiment_id"],
        "status": (
            "insufficient_data"
            if result["status"] != "ok"
            else "ready" if observed or predicted else "empty"
        ),
        **{
            key: result[key]
            for key in (
                "data_kind",
                "topic_id",
                "unit",
                "cutoff",
                "dataset_version",
                "series_version",
                "topic_definition_version",
            )
        },
        "observed": observed,
        "forecast": predicted,
        "explanation": explanation,
        "coverage_policy": series["coverage_evidence"],
    }
