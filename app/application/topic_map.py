"""Read a frozen NMF release without fitting or changing its assignments."""

import json
import math
from collections import Counter

from app.domain.common import AnalyticsError, fingerprint


def frozen_map(archive, release, start=None, end=None, threshold=0.2):
    if start is not None and end is not None and start > end:
        raise AnalyticsError("invalid_year_range", "Start year exceeds end year")
    if not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise AnalyticsError("invalid_similarity", "Threshold must be in [0,1]")
    study = json.loads(archive.read_blob(release, "study_results"))
    digest = study.pop("report_sha256", None)
    if fingerprint(study) != digest:
        raise AnalyticsError("study_integrity", "Study fingerprint differs")
    model_id = study["topic_model_id"]
    model = archive.read_topic_model(release, model_id)
    if fingerprint(model) != model_id or model["format"] != "nmf-json-v1":
        raise AnalyticsError("map_model_integrity", "Expected verified NMF model")
    documents = archive.read_table(release, "silver_prepared_documents")
    assignments = archive.read_table(release, "silver_topic_assignments")
    index = {d["document_id"]: d for d in documents}
    assigned = {a["document_id"]: a for a in assignments}
    if (
        len(index) != len(documents)
        or len(assigned) != len(assignments)
        or set(index) != set(assigned)
    ):
        raise AnalyticsError(
            "map_assignment_integrity", "Unique matching documents required"
        )
    topics = study["topics"]
    vectors = model["components"]
    if len(vectors) != len(topics):
        raise AnalyticsError("map_model_integrity", "Topic dimensions differ")
    counts = Counter()
    selected = []
    all_counts = Counter()
    for key, document in index.items():
        assignment = assigned[key]
        weights = json.loads(assignment["weights"])
        if len(weights) != len(topics) or any(
            not math.isfinite(w) or w < 0 for w in weights
        ):
            raise AnalyticsError(
                "map_assignment_integrity", "Invalid nonnegative weights"
            )
        topic = (
            "topic-" + str(max(range(len(weights)), key=weights.__getitem__))
            if any(weights)
            else None
        )
        if topic != assignment["topic_id"]:
            raise AnalyticsError(
                "map_assignment_integrity", "Frozen assignment differs from argmax"
            )
        all_counts[(document["year"], topic)] += 1
        if (start is None or document["year"] >= start) and (
            end is None or document["year"] <= end
        ):
            selected.append({**document, "topic_id": topic})
            counts[topic] += 1
    for point in archive.read_table(release, "gold_annual_series"):
        if point["count"] != all_counts[(point["year"], point["topic_id"])]:
            raise AnalyticsError(
                "map_series_integrity", "Map and annual series disagree"
            )
    denominator = len(selected)
    nodes = [
        {
            "topic_id": t["topic_id"],
            "terms": t["terms"],
            "count": counts[t["topic_id"]],
            "share": counts[t["topic_id"]] / denominator if denominator else 0,
        }
        for t in topics
    ]
    norms = [math.sqrt(math.fsum(v * v for v in vector)) for vector in vectors]
    if any(not math.isfinite(n) or n <= 0 for n in norms):
        raise AnalyticsError(
            "map_model_integrity", "Nonzero finite topic vectors required"
        )
    edges = []
    for i, a in enumerate(nodes):
        for j in range(i + 1, len(nodes)):
            weight = min(
                1.0,
                max(
                    0.0,
                    math.fsum(
                        x * y for x, y in zip(vectors[i], vectors[j], strict=True)
                    )
                    / (norms[i] * norms[j]),
                ),
            )
            if weight >= threshold:
                edges.append(
                    {
                        "source": a["topic_id"],
                        "target": nodes[j]["topic_id"],
                        "weight": weight,
                    }
                )
    result = {
        "release_id": release["release_id"],
        "model_id": model_id,
        "study_run_id": study["run_id"],
        "start_year": start,
        "end_year": end,
        "available_years": sorted({d["year"] for d in documents}),
        "threshold": threshold,
        "denominator": denominator,
        "unassigned": counts[None],
        "nodes": nodes,
        "edges": edges,
        "space": "cosine_normalized_nmf_tfidf_components",
        "assignment": "exclusive_argmax_lowest_index_tie_zero_unassigned",
        "coverage": "prepared snapshot; publication year; population coverage unknown",
        "interpretation": (
            "topic similarity; not causality, forecast or predictive attribution"
        ),
    }
    return result, selected
