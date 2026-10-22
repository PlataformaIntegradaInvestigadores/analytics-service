"""Explicit local experiment adapter: python -m app.experiments --help."""

import argparse
import sqlite3
import sys
from pathlib import Path

from pydantic import ValidationError

from app.application.presentation import explanation_state
from app.core.json_io import read_json_file
from app.data.experiments import KINDS, ExperimentStore
from app.domain.common import AnalyticsError, canonical_json


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    save = commands.add_parser("save")
    save.add_argument("--input", type=Path, required=True)
    query = commands.add_parser("list")
    query.add_argument("--limit", type=int, default=20)
    query.add_argument("--offset", type=int, default=0)
    query.add_argument("--kind", choices=list(KINDS))
    query.add_argument("--data-kind", choices=["synthetic", "empirical"])
    query.add_argument("--topic-id")
    query.add_argument("--status", choices=["ok", "insufficient_data", "declared"])
    for name in ("show", "explanation", "dashboard", "replay"):
        command = commands.add_parser(name)
        command.add_argument("--id", required=True)
        if name == "explanation":
            command.add_argument(
                "--scope", choices=["local", "global"], default="local"
            )
        if name == "dashboard":
            command.add_argument("--start")
            command.add_argument("--end")
    for command in (
        save,
        query,
        *[
            commands.choices[name]
            for name in ("show", "explanation", "dashboard", "replay")
        ],
    ):
        command.add_argument("--database", type=Path, required=True)
    args = parser.parse_args(argv)
    database = ExperimentStore(args.database)
    try:
        if args.operation == "save":
            result = database.save(read_json_file(args.input))
        elif args.operation == "list":
            result = database.query(
                **{
                    key: getattr(args, key)
                    for key in (
                        "limit",
                        "offset",
                        "kind",
                        "data_kind",
                        "topic_id",
                        "status",
                    )
                }
            )
        elif args.operation == "replay":
            result = database.replay(args.id)
        else:
            artifact = database.load(args.id)
            if args.operation == "explanation":
                result = explanation_state(artifact, args.scope)
            elif args.operation == "dashboard":
                result = database.dashboard(args.id, args.start, args.end)
            else:
                result = artifact
        print(canonical_json(result))
        return 1 if result.get("status") == "mismatch" else 0
    except (AnalyticsError, ValidationError, OSError, sqlite3.Error) as exc:
        print(
            canonical_json(
                {"error": getattr(exc, "code", "invalid_input"), "message": str(exc)}
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
