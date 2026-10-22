"""Read-only export inspection: python -m app.imports --help."""

import argparse
import sys
from pathlib import Path

from pydantic import Field, ValidationError

from app.core.json_io import read_json_file
from app.data.exports import field_dictionary, inspect_export
from app.domain.common import AnalyticsError, canonical_json
from app.schemas.analytics import Contract


class Mapping(Contract):
    fields: dict[str, str]
    ignored_columns: list[str] = Field(default_factory=list)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["dictionary", "inspect"])
    parser.add_argument("--input", type=Path)
    parser.add_argument("--format", choices=["jsonl", "csv"])
    parser.add_argument("--data-kind", choices=["empirical", "synthetic"])
    parser.add_argument("--mapping", type=Path)
    parser.add_argument("--batch-size", type=int, default=250)
    args = parser.parse_args(argv)
    try:
        if args.operation == "dictionary":
            if (
                args.input
                or args.format
                or args.data_kind
                or args.mapping
                or args.batch_size != 250
            ):
                raise AnalyticsError(
                    "invalid_arguments", "dictionary accepts no import options"
                )
            result = field_dictionary()
        else:
            if not args.input or not args.format or not args.data_kind:
                raise AnalyticsError(
                    "invalid_arguments", "Declare input, format and data-kind"
                )
            mapping = (
                Mapping.model_validate(read_json_file(args.mapping))
                if args.mapping
                else None
            )
            result = inspect_export(
                args.input,
                args.format,
                args.data_kind,
                mapping.fields if mapping else None,
                mapping.ignored_columns if mapping else None,
                args.batch_size,
            )
        print(canonical_json(result))
        return 1 if result.get("status") == "needs_correction" else 0
    except (AnalyticsError, ValidationError, OSError) as exc:
        print(
            canonical_json(
                {"error": getattr(exc, "code", "invalid_input"), "message": str(exc)}
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
