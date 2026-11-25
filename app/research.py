"""Import a locally authorized eight-table research corpus; no model fitting."""

import argparse
import sqlite3
import sys
from pathlib import Path

from app.data.research_corpus import ingest_research
from app.domain.common import AnalyticsError, canonical_json


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ingest", choices=["ingest"])
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--approval-reference", required=True)
    args = parser.parse_args(argv)
    try:
        report = ingest_research(
            args.directory, args.database, approval_reference=args.approval_reference
        )
        print(canonical_json(report))
        return 0
    except (AnalyticsError, OSError, sqlite3.Error) as exc:
        print(
            canonical_json(
                {
                    "error": getattr(exc, "code", "research_io_error"),
                    "message": str(exc),
                }
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
