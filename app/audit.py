"""Read-only environment, inventory, schema and reference-replay evidence."""

import argparse
import platform
import sqlite3
import sys
from importlib.metadata import version
from pathlib import Path

from app import __version__
from app.application.analysis import forecast_batch
from app.core.json_io import read_json_file
from app.core.provenance import (
    ROOT,
    environment_manifest,
    sha256_file,
    software_inventory,
    verify_environment,
)
from app.data.forecast_runs import ForecastRunStore
from app.domain.common import AnalyticsError, canonical_json


def replay_run(database: Path, run_id: str) -> dict:
    run = ForecastRunStore(database).load(run_id)
    changed = [
        relative
        for relative, digest in run["code_sha256"].items()
        if not (ROOT / "app" / relative).is_file()
        or not (ROOT / "app" / relative)
        .resolve()
        .is_relative_to((ROOT / "app").resolve())
        or sha256_file(ROOT / "app" / relative) != digest
    ]
    runtime = {
        "python": platform.python_version(),
        "service": __version__,
        "pydantic": version("pydantic"),
    }
    runtime_match = runtime == run["runtime"]
    matches = None
    if not changed and runtime_match:
        matches = canonical_json(forecast_batch(run["request"])) == canonical_json(
            run["result"]
        )
    return {
        "run_id": run_id,
        "data_kind": run["result"]["data_kind"],
        "integrity_verified": True,
        "changed_sources": changed,
        "runtime_match": runtime_match,
        "reexecuted": matches is not None,
        "result_match": matches,
        "status": (
            "drift"
            if changed or not runtime_match
            else "ok" if matches else "result_mismatch"
        ),
        "scope": (
            "Reference computation only; does not validate empirical predictive quality"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    environment = commands.add_parser("environment")
    environment.add_argument("--requirements", default="requirements-dev.txt")
    verify = commands.add_parser("verify-environment")
    verify.add_argument("--manifest", type=Path, required=True)
    commands.add_parser("inventory")
    schema = commands.add_parser("schema")
    schema.add_argument("--public-base-path", default="/api/v1")
    replay = commands.add_parser("replay")
    replay.add_argument("--database", type=Path, required=True)
    replay.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "environment":
            result = environment_manifest(entry=args.requirements)
        elif args.command == "verify-environment":
            result = verify_environment(read_json_file(args.manifest))
        elif args.command == "inventory":
            result = software_inventory()
        elif args.command == "schema":
            from app.core.config import Settings
            from app.main import create_app

            result = create_app(
                Settings(
                    _env_file=None,
                    environment="local",
                    public_base_path=args.public_base_path,
                )
            ).openapi()
        else:
            result = replay_run(args.database, args.run_id)
        print(canonical_json(result))
        return 0 if result.get("status", "ok") == "ok" else 1
    except (AnalyticsError, OSError, ValueError, sqlite3.Error, SyntaxError) as exc:
        print(
            canonical_json(
                {
                    "error": getattr(exc, "code", "invalid_audit_input"),
                    "message": str(exc),
                }
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
