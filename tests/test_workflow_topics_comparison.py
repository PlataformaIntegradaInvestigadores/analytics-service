"""Technical fixtures only; no fitted thematic model or empirical claims."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.application.analysis import (
    catalog_batch,
    catalog_series_batch,
    comparison_batch,
)
from app.domain.common import AnalyticsError
from app.schemas.workflow import (
    CatalogRequest,
    CatalogResult,
    ComparisonRequest,
    ComparisonResult,
    Topic,
)


@pytest.fixture
def catalog_request(series_request):
    return {
        "batch": series_request["batch"],
        "topics": [
            {
                "topic_id": "topic-a",
                "label": "Fixture A",
                "terms": ["synthetic", "example"],
            },
            {"topic_id": "topic-b", "label": "Fixture B", "terms": ["other"]},
        ],
        "assignments": series_request["assignments"],
        "method": "manual",
    }


@pytest.fixture
def comparison_request(series_request):
    return {
        "series": series_request,
        "topic_id": "topic-a",
        "validation_start": "2020-03",
        "validation_end": "2020-05",
        "final_test_start": "2020-06",
        "horizon": 1,
        "min_train": 2,
        "season_length": 2,
    }


def normalized(payload):
    return CatalogRequest.model_validate(payload).model_dump(mode="json")


def test_catalog_identity_order_and_partial_assignments(catalog_request):
    result = CatalogResult.model_validate(
        catalog_batch(normalized(catalog_request))
    ).model_dump()
    permuted = deepcopy(catalog_request)
    permuted["topics"].reverse()
    permuted["topics"][1]["terms"].reverse()
    permuted["batch"]["records"].reverse()
    assert catalog_batch(normalized(permuted)) == result
    assert "no topic model fitted" in result["evidence_status"]
    assert result["unassigned_document_ids"] == []
    del permuted["assignments"][next(iter(permuted["assignments"]))]
    assert len(catalog_batch(normalized(permuted))["unassigned_document_ids"]) == 1


@pytest.mark.parametrize(
    "change,code",
    [
        ({"method": "unsupported"}, "invalid_topic_method"),
        ({"topics": []}, "invalid_topics"),
        (
            {"topics": [{"topic_id": "a", "label": "A", "terms": ["x"]}] * 2},
            "invalid_topics",
        ),
        (
            {"topics": [{"topic_id": " ", "label": "A", "terms": ["x"]}]},
            "invalid_topics",
        ),
        (
            {"topics": [{"topic_id": "a", "label": " ", "terms": ["x"]}]},
            "invalid_topics",
        ),
        (
            {"topics": [{"topic_id": "a", "label": "A", "terms": ["x", "X"]}]},
            "invalid_topics",
        ),
        (
            {"topics": [{"topic_id": "a", "label": "A", "terms": [" "]}]},
            "invalid_topics",
        ),
        ({"assignments": {"unknown": "topic-a"}}, "invalid_assignment"),
        (
            {"assignments": {"doi:10.9999/synthetic-1-0": "unknown"}},
            "invalid_assignment",
        ),
        ({"fit_document_ids": ["missing"]}, "invalid_fit_documents"),
        ({"model_version": "v1"}, "unexpected_model_provenance"),
        ({"fit_cutoff": "2020-01-31"}, "unexpected_model_provenance"),
        ({"method": "topic_model"}, "missing_model_provenance"),
    ],
)
def test_invalid_catalog_evidence(catalog_request, change, code):
    with pytest.raises(AnalyticsError) as exc:
        catalog_batch({**catalog_request, **change})
    assert exc.value.code == code


def test_catalog_rejects_curation_failures_and_duplicate_fit_ids(catalog_request):
    catalog_request["batch"]["records"].append({"title": "invalid"})
    with pytest.raises(AnalyticsError, match="rejected corpus"):
        catalog_batch(catalog_request)
    catalog_request["batch"]["records"].pop()
    identifier = next(iter(catalog_request["assignments"]))
    with pytest.raises(AnalyticsError, match="unique known"):
        catalog_batch({**catalog_request, "fit_document_ids": [identifier, identifier]})


@pytest.mark.parametrize("missing", ["available_on", "publication_date"])
def test_inferred_topics_require_historical_evidence(catalog_request, missing):
    identifier = next(iter(catalog_request["assignments"]))
    catalog_request.update(
        method="topic_model",
        model_version="declared-only-v1",
        fit_document_ids=[identifier],
        fit_cutoff="2020-01-31",
    )
    result = catalog_batch(normalized(catalog_request))
    assert result["method"] == "topic_model"
    catalog_request["batch"]["records"][0][missing] = None
    with pytest.raises(AnalyticsError, match="published and available"):
        catalog_batch(normalized(catalog_request))


def test_model_catalog_cutoffs_and_series(catalog_request):
    request = {
        "catalog": normalized(catalog_request),
        "start": "2020-01",
        "end": "2020-06",
        "covered_periods": [f"2020-{m:02}" for m in range(1, 7)],
    }
    result = catalog_series_batch(request)
    assert (
        result["topic_definition_version"]
        == catalog_batch(request["catalog"])["topic_definition_version"]
    )
    assert len(result["points"]) == 12
    request["catalog"].update(
        method="topic_model",
        model_version="declared-v1",
        fit_document_ids=[next(iter(catalog_request["assignments"]))],
        fit_cutoff="2020-01-31",
    )
    with pytest.raises(AnalyticsError, match="precede the series"):
        catalog_series_batch(request)
    request["start"] = "2020-02"
    request["covered_periods"].pop(0)
    assert catalog_series_batch(request)["start"] == "2020-02"
    request["catalog"]["fit_cutoff"] = "2020-01-01"
    with pytest.raises(AnalyticsError, match="published and available"):
        catalog_series_batch(request)


@pytest.mark.parametrize("terms", [[" "], ["a" * 257]])
def test_term_contract_limits(terms):
    with pytest.raises(ValidationError):
        Topic(topic_id="a", label="A", terms=terms)


def test_keyword_catalog_remains_distinct(catalog_request):
    manual = catalog_batch(normalized(catalog_request))
    catalog_request["method"] = "keywords"
    for record in catalog_request["batch"]["records"]:
        record["keywords"] = ["Synthetic"]
    keyword = catalog_batch(normalized(catalog_request))
    assert keyword["topic_definition_version"] != manual["topic_definition_version"]
    assert keyword["model_version"] is None


def test_keywords_cannot_be_claimed_without_source_evidence(catalog_request):
    catalog_request["method"] = "keywords"
    with pytest.raises(AnalyticsError, match="source keyword"):
        catalog_batch(normalized(catalog_request))


def test_comparison_uses_common_origins_and_exact_paired_errors(comparison_request):
    payload = ComparisonRequest.model_validate(comparison_request).model_dump(
        mode="json"
    )
    result = ComparisonResult.model_validate(comparison_batch(payload)).model_dump()
    assert result["common_origins"] == ["2020-02", "2020-03", "2020-04"]
    assert result["metrics"]["last_value"]["mae"] == 1
    assert result["metrics"]["seasonal_naive"]["mae"] == 2
    assert result["preferred_by_validation_mae"] == "last_value"
    assert all(
        point["period"] < "2020-06"
        for fold in result["paired_folds"]
        for points in fold["predictions"].values()
        for point in points
    )
    # A valid change in reserved final observations cannot influence comparison ID.
    altered = deepcopy(payload)
    removed = altered["series"]["batch"]["records"].pop()
    del altered["series"]["assignments"]["doi:" + removed["doi"]]
    other = comparison_batch(altered)
    assert other["comparison_id"] == result["comparison_id"]
    assert other["series_version"] != result["series_version"]


def test_comparison_reports_unpaired_and_missing_origins(comparison_request):
    comparison_request["season_length"] = 3
    result = comparison_batch(comparison_request)
    assert result["omitted"]["last_value"]["unpaired_origins"] == ["2020-02"]
    assert result["common_origins"] == ["2020-03", "2020-04"]
    comparison_request["series"]["covered_periods"].remove("2020-03")
    missing = comparison_batch(comparison_request)
    assert missing["status"] == "insufficient_data"
    assert missing["preferred_by_validation_mae"] is None
    assert missing["metrics"]["last_value"]["mae"] is None


def test_comparison_zero_series_and_overlapping_horizons(comparison_request):
    comparison_request["topic_id"] = "topic-b"
    comparison_request["horizon"] = 2
    result = comparison_batch(comparison_request)
    assert result["preferred_by_validation_mae"] == "tie"
    assert result["metrics"]["last_value"]["n"] == 4
    assert result["metrics"]["last_value"]["wape"] is None
    assert result["metrics"]["last_value"]["mean_fold_mase_lag1"] is None


def test_seasonal_reference_can_win(comparison_request):
    from app.domain.comparison import compare_references

    points = [{"period": f"2020-{m:02}", "value": (m % 2) * 10} for m in range(1, 7)]
    result = compare_references(
        points,
        validation_start="2020-03",
        validation_end="2020-05",
        final_test_start="2020-06",
        horizon=1,
        min_train=2,
        season_length=2,
    )
    assert result["preferred_by_validation_mae"] == "seasonal_naive"


def test_comparison_respects_final_test_boundary(comparison_request):
    comparison_request["validation_end"] = comparison_request["final_test_start"]
    with pytest.raises(AnalyticsError, match="reserved final test"):
        comparison_batch(comparison_request)


@pytest.mark.parametrize("availability", [None, "2020-02-01"])
def test_comparison_rejects_unverified_or_delayed_history(
    comparison_request, availability
):
    comparison_request["series"]["batch"]["records"][0]["available_on"] = availability
    with pytest.raises(AnalyticsError) as exc:
        comparison_batch(comparison_request)
    assert exc.value.code == "unverified_series_availability"


def test_missing_date_documents_are_not_silently_historical(comparison_request):
    comparison_request["series"]["batch"]["records"][0]["publication_date"] = None
    comparison_request["series"]["batch"]["records"][0]["available_on"] = None
    result = comparison_batch(comparison_request)
    assert result["curation_quality"]["missing_publication_dates"] == 1
    assert (
        result["availability_policy"] == "frozen_counts_known_by_publication_month_end"
    )
