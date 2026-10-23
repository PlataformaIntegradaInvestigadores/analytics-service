"""Local Centinela export adapter; no remote access or model fitting."""

import argparse
import sqlite3
import sys
from pathlib import Path

from app.data.centinela import descriptor_counts, ingest, inspect
from app.domain.common import AnalyticsError, canonical_json


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    for name in ("inspect", "ingest"):
        command = commands.add_parser(name)
        command.add_argument("--directory", type=Path, required=True)
        command.add_argument("--batch-size", type=int, default=500)
        if name == "ingest":
            command.add_argument("--database", type=Path, required=True)
    counts = commands.add_parser("descriptors")
    counts.add_argument("--database", type=Path, required=True)
    counts.add_argument("--descriptor", action="append", required=True)
    args = parser.parse_args(argv)
    try:
        if args.operation == "inspect":
            result = inspect(args.directory, args.batch_size)
        elif args.operation == "ingest":
            result = ingest(args.directory, args.database, args.batch_size)
        else:
            result = descriptor_counts(args.database, args.descriptor)
        print(canonical_json(result))
        return 0
    except (AnalyticsError, OSError, sqlite3.Error) as exc:
        print(
            canonical_json(
                {"error": getattr(exc, "code", "corpus_io_error"), "message": str(exc)}
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
