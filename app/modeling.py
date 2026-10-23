"""Explicit local topic modeling CLI. No automatic empirical corpus training."""

import argparse
from pathlib import Path

from pydantic import Field, ValidationError

from app.application.modeling import bertopic_capability, fit_nmf, infer_nmf
from app.core.json_io import read_json_file
from app.core.provenance import source_files
from app.data.models import ModelStore
from app.domain.common import AnalyticsError, canonical_json
from app.schemas.analytics import Contract


class TextDocument(Contract):
    document_id: str = Field(min_length=1, max_length=256)
    text: str = Field(min_length=1, max_length=100000)
    publication_date: str | None = None
    available_on: str | None = None


class ModelInput(Contract):
    documents: list[TextDocument] = Field(min_length=2, max_length=100000)
    fit_ids: list[str] = Field(min_length=2, max_length=100000)
    workset_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    topics: int = Field(default=2, ge=2, le=100, strict=True)
    seed: int = Field(default=42, ge=0, lt=2**32, strict=True)
    cutoff: str | None = None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("capabilities")
    for name in ("fit", "infer", "show"):
        command = commands.add_parser(name)
        command.add_argument("--database", type=Path, required=True)
        if name != "show":
            command.add_argument("--input", type=Path, required=True)
        if name != "fit":
            command.add_argument("--id", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "capabilities":
            result = bertopic_capability()
        else:
            store = ModelStore(args.database)
            if args.command == "fit":
                request = ModelInput.model_validate(read_json_file(args.input))
                result = store.save(
                    fit_nmf(**request.model_dump(), software=source_files())
                )
                result = {
                    k: result[k]
                    for k in ("model_id", "workset_id", "method", "purpose")
                }
            else:
                result = store.load(args.id)
                if args.command == "infer":
                    documents = [
                        TextDocument.model_validate(d).model_dump()
                        for d in read_json_file(args.input)
                    ]
                    result = infer_nmf(result, documents)
        print(canonical_json(result))
        return 0
    except (AnalyticsError, ValidationError, OSError, ValueError, TypeError) as exc:
        print(
            canonical_json(
                {
                    "status": "error",
                    "code": getattr(exc, "code", "invalid_input"),
                    "message": str(exc),
                }
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
