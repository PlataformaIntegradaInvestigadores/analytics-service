"""Document queries and immutable preparation, with no model training."""

import argparse
import sqlite3
import sys
from pathlib import Path

from pydantic import ValidationError

from app.core.json_io import read_json_file
from app.data import documents, quality
from app.domain.common import AnalyticsError, canonical_json


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation",
        choices=[
            "articles",
            "article",
            "descriptors",
            "summary",
            "preview",
            "prepare",
            "workset",
            "protocol",
            "evaluate",
            "quality",
        ],
    )
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--id")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--year", type=int)
    parser.add_argument("--author")
    parser.add_argument("--descriptor")
    args = parser.parse_args(argv)
    try:
        op = args.operation
        uses_input = op in ("preview", "prepare", "protocol", "evaluate")
        if (
            bool(args.input) != uses_input
            or bool(args.output) != (op == "prepare")
            or bool(args.id) != (op == "article")
        ):
            raise AnalyticsError(
                "invalid_arguments", "Check input/output/id for selected operation"
            )
        if (
            op not in ("articles", "descriptors")
            and (args.limit != 20 or args.offset != 0)
            or op != "articles"
            and any(
                value is not None for value in (args.year, args.author, args.descriptor)
            )
        ):
            raise AnalyticsError(
                "invalid_arguments", "Filters/pagination do not apply to this operation"
            )
        if op == "articles":
            result = documents.article_page(
                args.database,
                limit=args.limit,
                offset=args.offset,
                year=args.year,
                author=args.author,
                descriptor=args.descriptor,
            )
        elif op == "article":
            result = documents.article_detail(args.database, args.id)
        elif op == "descriptors":
            result = documents.descriptor_page(args.database, args.limit, args.offset)
        elif op == "summary":
            result = documents.summary(args.database)
        elif op == "quality":
            result = quality.quality_report(args.database)
        elif op == "workset":
            result = documents.working_manifest(args.database)
        else:
            payload = read_json_file(args.input)
            if op == "prepare":
                result = documents.save_workset(args.database, args.output, payload)
            else:
                operation = {
                    "preview": documents.preview,
                    "protocol": documents.candidate_protocol,
                    "evaluate": documents.evaluate_outputs,
                }[op]
                result = operation(args.database, payload)
        print(canonical_json(result))
        return 0
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
