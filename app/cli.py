"""Explicit local adapter: python -m app.cli OPERATION --input request.json."""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from pydantic import ValidationError

from app.application import analysis
from app.core.json_io import read_json_file
from app.data.forecast_runs import ForecastRunStore
from app.data.snapshots import SnapshotStore
from app.domain.common import AnalyticsError, canonical_json
from app.schemas.analytics import (
    BacktestRequest,
    BatchRequest,
    FeaturesRequest,
    ForecastRequest,
    SeriesRequest,
    SplitRequest,
)

OPERATIONS = {
    "curate": (BatchRequest, analysis.curate_batch),
    "split": (SplitRequest, analysis.split_batch),
    "series": (SeriesRequest, analysis.aggregate_batch),
    "forecast": (ForecastRequest, analysis.forecast_batch),
    "backtest": (BacktestRequest, analysis.backtest_batch),
    "features": (FeaturesRequest, analysis.features_batch),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation", choices=[*OPERATIONS, "restore", "restore-forecast"]
    )
    parser.add_argument(
        "--input", type=Path, help="JSON request; required except for restore"
    )
    parser.add_argument("--database", type=Path, help="Explicit local SQLite file")
    parser.add_argument("--batch-id", help="Content-addressed batch to restore")
    parser.add_argument(
        "--run-id", help="Content-addressed reference forecast to restore"
    )
    args = parser.parse_args(argv)
    try:
        if args.operation == "restore-forecast":
            if args.input or args.batch_id or not args.database or not args.run_id:
                raise AnalyticsError(
                    "invalid_arguments",
                    "restore-forecast requires database and run-id only",
                )
            result = ForecastRunStore(args.database).load(args.run_id)
        elif args.operation == "restore":
            if args.input or args.run_id or not args.database or not args.batch_id:
                raise AnalyticsError(
                    "invalid_arguments", "restore requires database and batch-id only"
                )
            if not args.database.is_file():
                raise AnalyticsError("snapshot_not_found", "Database does not exist")
            result = SnapshotStore(args.database).load(args.batch_id)
        else:
            if not args.input or args.batch_id or args.run_id:
                raise AnalyticsError(
                    "invalid_arguments", "An input file is required; no batch-id"
                )
            schema, operation = OPERATIONS[args.operation]
            payload = schema.model_validate(read_json_file(args.input)).model_dump()
            if args.database:
                if args.operation == "curate":
                    result = SnapshotStore(args.database).save(**payload)
                elif args.operation == "forecast":
                    result = ForecastRunStore(args.database).save(payload)
                else:
                    raise AnalyticsError(
                        "invalid_arguments",
                        "Only curate and forecast persist artifacts",
                    )
            else:
                result = operation(payload)
        print(canonical_json(result))
        return 0
    except (
        AnalyticsError,
        ValidationError,
        OSError,
        sqlite3.Error,
        json.JSONDecodeError,
    ) as exc:
        print(
            canonical_json(
                {"error": getattr(exc, "code", "invalid_input"), "message": str(exc)}
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
