"""Read-only software inventory and environment comparison, without Git or network."""

import ast
import hashlib
import platform
import re
import sqlite3
from importlib import metadata
from pathlib import Path

from app import __version__
from app.domain.common import AnalyticsError, fingerprint

ROOT = Path(__file__).resolve().parents[2]
CONFIGURATION_FILES = (
    "requirements.txt",
    "requirements-dev.txt",
    "constraints.txt",
    "pyproject.toml",
    "Dockerfile",
    "docker-compose.yml",
    ".gitattributes",
    ".github/workflows/ci.yml",
)
MANIFEST_VERSION = "software-environment-v1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(65536):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_path(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise AnalyticsError(
            "invalid_manifest_path", "Path leaves the project directory"
        )
    return path


def source_files(root: Path = ROOT) -> dict[str, str]:
    paths = sorted((root / "app").rglob("*.py"))
    paths.extend(
        root / relative
        for relative in CONFIGURATION_FILES
        if (root / relative).is_file()
    )
    return {
        path.relative_to(root).as_posix(): sha256_file(
            _safe_path(root, str(path.relative_to(root)))
        )
        for path in paths
    }


def declared_dependencies(root: Path, entry: str) -> tuple[dict, dict]:
    root = root.resolve()
    required, constraints = {}, {}
    visited = set()

    def visit(relative: str, constrained: bool, active: set):
        path = _safe_path(root, relative)
        key = (path, constrained)
        if key in active:
            raise AnalyticsError(
                "requirements_cycle", "Recursive requirement file cycle"
            )
        if key in visited:
            return
        active = active | {key}
        if not path.is_file():
            raise AnalyticsError(
                "requirements_missing", "A declared requirement file is absent"
            )
        for raw in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw.partition("#")[0].strip()
            if not line:
                continue
            include = re.fullmatch(r"(-r|-c|--requirement|--constraint)\s+(.+)", line)
            if include:
                child = _safe_path(root, str(path.parent / include[2]))
                visit(
                    str(child.relative_to(root)),
                    constrained or include[1] in ("-c", "--constraint"),
                    active,
                )
                continue
            pin = re.fullmatch(
                r"([A-Za-z0-9][A-Za-z0-9_.-]*)==([A-Za-z0-9][A-Za-z0-9_.+!-]*)", line
            )
            if not pin:
                raise AnalyticsError(
                    "unsupported_requirement",
                    "Only exact local package pins are supported",
                )
            name = re.sub(r"[-_.]+", "-", pin[1]).lower()
            mapping = constraints if constrained else required
            if name in mapping and mapping[name] != pin[2]:
                raise AnalyticsError("conflicting_pins", "Conflicting package versions")
            mapping[name] = pin[2]
        visited.add(key)

    visit(entry, False, set())
    if any(
        name in constraints and constraints[name] != value
        for name, value in required.items()
    ):
        raise AnalyticsError(
            "conflicting_pins", "Requirements and constraints disagree"
        )
    return dict(sorted(required.items())), dict(sorted(constraints.items()))


def environment_manifest(
    root: Path = ROOT, entry: str = "requirements-dev.txt"
) -> dict:
    root = root.resolve()
    required, constraints = declared_dependencies(root, entry)
    packages = {}
    for distribution in metadata.distributions():
        name = re.sub(r"[-_.]+", "-", distribution.metadata["Name"]).lower()
        packages[name] = distribution.version
    packages = dict(sorted(packages.items()))
    mismatches = [
        {"package": name, "expected": expected, "installed": packages.get(name)}
        for name, expected in sorted((constraints | required).items())
        if (name in required or name in packages) and packages.get(name) != expected
    ]
    python = platform.python_version()
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "service_version": __version__,
        "python": python,
        "python_target": "3.11",
        "sqlite": sqlite3.sqlite_version,
        "platform": {"system": platform.system(), "machine": platform.machine()},
        "entry": entry,
        "required": required,
        "constraints": constraints,
        "installed_packages": packages,
        "files_sha256": source_files(root),
        "dependency_mismatches": mismatches,
        "status": "ok" if python.startswith("3.11.") and not mismatches else "mismatch",
        "scope": "Software evidence only; no corpus or model evaluation is performed",
    }
    return {**manifest, "manifest_sha256": fingerprint(manifest)}


def verify_environment(expected: dict, root: Path = ROOT) -> dict:
    if not isinstance(expected, dict):
        raise AnalyticsError(
            "invalid_environment_manifest", "Manifest must be an object"
        )
    try:
        content = {
            key: value for key, value in expected.items() if key != "manifest_sha256"
        }
        if fingerprint(content) != expected["manifest_sha256"]:
            raise ValueError
        if expected["manifest_version"] != MANIFEST_VERSION:
            raise ValueError
        current = environment_manifest(root, expected["entry"])
        if set(expected) != set(current):
            raise ValueError("Incomplete or unsupported manifest fields")
        compared = (
            "python",
            "sqlite",
            "service_version",
            "required",
            "constraints",
            "installed_packages",
            "files_sha256",
        )
        differences = [key for key in compared if current[key] != expected[key]]
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, AnalyticsError):
            raise
        raise AnalyticsError(
            "invalid_environment_manifest", "Invalid manifest identity or format"
        ) from exc
    return {
        "status": "ok" if not differences and current["status"] == "ok" else "mismatch",
        "differences": differences,
        "platform_changed": current["platform"] != expected["platform"],
        "expected_manifest": expected["manifest_sha256"],
        "current_manifest": current["manifest_sha256"],
        "policy": (
            "Exact source, package, Python and SQLite comparison; "
            "platform reported separately"
        ),
    }


def software_inventory(root: Path = ROOT) -> dict:
    modules, violations = [], []
    for path in sorted((root / "app").rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        safe = _safe_path(root, relative)
        tree = ast.parse(safe.read_text(encoding="utf-8-sig"), filename=relative)
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.add("." * node.level + (node.module or ""))
        layer = relative.split("/")[1] if "/" in relative[4:] else "entrypoint"
        for dependency in sorted(imports):
            if layer in ("domain", "application") and (
                dependency.startswith(".")
                or dependency.split(".")[0]
                in (
                    "fastapi",
                    "pydantic",
                    "pydantic_settings",
                    "sqlite3",
                    "httpx",
                    "requests",
                    "neo4j",
                )
                or dependency.startswith("app.")
                and not any(
                    dependency == prefix or dependency.startswith(prefix + ".")
                    for prefix in (
                        ("app.domain", "app.application")
                        if layer == "application"
                        else ("app.domain",)
                    )
                )
            ):
                violations.append({"file": relative, "dependency": dependency})
        modules.append(
            {
                "file": relative,
                "sha256": sha256_file(safe),
                "layer": layer,
                "imports": sorted(imports),
            }
        )
    return {
        "inventory_version": "software-inventory-v1",
        "modules": modules,
        "boundary_violations": violations,
        "status": "ok" if not violations else "mismatch",
        "evidence": (
            "Local source inspection; no external service connectivity was tested"
        ),
    }
