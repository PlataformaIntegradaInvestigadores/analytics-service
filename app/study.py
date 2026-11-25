"""Execute a prespecified local study without data downloads."""

import argparse
import sqlite3
import sys
from pathlib import Path

from pydantic import ValidationError

from app.core.json_io import read_json_file
from app.domain.common import AnalyticsError, canonical_json
from app.research_execution import run_study


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = run_study(args.corpus, args.output, read_json_file(args.protocol))
        print(canonical_json(result))
        return 0
    except (AnalyticsError, ValidationError, OSError, sqlite3.Error) as exc:
        print(
            canonical_json(
                {"error": getattr(exc, "code", "invalid_study"), "message": str(exc)}
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
