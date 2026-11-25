"""Summarize actual anonymized sessions once collected; never generate responses."""

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

from app.core.provenance import sha256_file


def summarize(path):
    tasks = defaultdict(list)
    seen = set()
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != [
            "participant_id",
            "task_id",
            "success",
            "seconds",
            "comprehension",
            "actionability",
        ]:
            raise ValueError("Use the documented six-column anonymized session schema")
        for row in reader:
            key = (row["participant_id"], row["task_id"])
            if not all(key) or key in seen:
                raise ValueError("Unique nonempty participant/task pairs required")
            seen.add(key)
            values = {}
            for field in ["success", "seconds", "comprehension", "actionability"]:
                value = None if row[field] == "" else float(row[field])
                if value is not None and (not math.isfinite(value) or value < 0):
                    raise ValueError("Finite nonnegative observations required")
                if field == "success" and value not in (None, 0, 1):
                    raise ValueError("Success must be 0 or 1")
                if field in ("comprehension", "actionability") and value not in (
                    None,
                    1,
                    2,
                    3,
                    4,
                    5,
                ):
                    raise ValueError("Ratings must be integers 1..5 or missing")
                values[field] = value
            tasks[row["task_id"]].append(values)
    if not seen:
        raise ValueError("No actual session rows supplied")
    result = {}
    for task, rows in sorted(tasks.items()):
        result[task] = {"observations": len(rows), "measures": {}}
        for field in ["success", "seconds", "comprehension", "actionability"]:
            observed = [r[field] for r in rows if r[field] is not None]
            result[task]["measures"][field] = {
                "n": len(observed),
                "missing": len(rows) - len(observed),
                "mean": statistics.mean(observed) if observed else None,
                "median": statistics.median(observed) if observed else None,
                "min": min(observed) if observed else None,
                "max": max(observed) if observed else None,
            }
    return {
        "source_sha256": sha256_file(path),
        "participants": len({p for p, _ in seen}),
        "tasks": result,
        "analysis": "descriptive; no causal or population inference",
        "instrument": "proposed ad hoc rubric; tutor review required before collection",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("responses", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = summarize(args.responses)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
