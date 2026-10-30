"""
Flyway Migration Name Validator Module.

Centralized source of truth for matching, parsing, and validating Flyway migration
filename formats (versioned, undo, repeatable, and callback scripts).
"""

from dataclasses import dataclass
import argparse
import os
import pathlib
import re
import sys
from typing import Optional, List, Tuple, Dict, Iterable, Sequence

# Regex definitions for Flyway migration patterns
VERSIONED_RE = re.compile(r"^V([0-9]+(?:\.[0-9]+)*)__(.+)\.sql$", re.IGNORECASE)
UNDO_RE = re.compile(r"^U([0-9]+(?:\.[0-9]+)*)__(.+)\.sql$", re.IGNORECASE)
REPEATABLE_RE = re.compile(r"^R__(.+)\.sql$", re.IGNORECASE)
CALLBACK_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*\.sql$", re.IGNORECASE)

# Regex definitions for detecting malformed single '_' separator migration filenames
SINGLE_UNDERSCORE_VERSIONED_RE = re.compile(r"^V([0-9]+(?:\.[0-9]+)*)_(?!_)(.+)\.sql$", re.IGNORECASE)
SINGLE_UNDERSCORE_UNDO_RE = re.compile(r"^U([0-9]+(?:\.[0-9]+)*)_(?!_)(.+)\.sql$", re.IGNORECASE)


@dataclass
class FlywayMigrationInfo:
    migration_type: str  # "versioned", "undo", "repeatable", "callback"
    version: Optional[str]  # e.g., "1.0001", "202408160101.1", "999999999999.1"
    description: str
    raw_filename: str
    filepath: Optional[pathlib.Path] = None


def parse_migration_filename(target: str | pathlib.Path) -> Optional[FlywayMigrationInfo]:
    """Parse a migration filename or Path object and return FlywayMigrationInfo if valid.

    :param target: Filename string or pathlib.Path object
    :return: FlywayMigrationInfo instance if matched, otherwise None
    """
    path = pathlib.Path(target) if isinstance(target, str) else target
    name = path.name

    vm = VERSIONED_RE.match(name)
    if vm:
        return FlywayMigrationInfo(
            migration_type="versioned",
            version=vm.group(1),
            description=vm.group(2),
            raw_filename=name,
            filepath=path,
        )

    um = UNDO_RE.match(name)
    if um:
        return FlywayMigrationInfo(
            migration_type="undo",
            version=um.group(1),
            description=um.group(2),
            raw_filename=name,
            filepath=path,
        )

    rm = REPEATABLE_RE.match(name)
    if rm:
        return FlywayMigrationInfo(
            migration_type="repeatable",
            version=None,
            description=rm.group(1),
            raw_filename=name,
            filepath=path,
        )

    # Note: callbacks are usually in a callbacks directory, but match by filename pattern
    cm = CALLBACK_RE.match(name)
    if cm and not name.lower().startswith(("v", "u", "r")):
        return FlywayMigrationInfo(
            migration_type="callback",
            version=None,
            description=path.stem,
            raw_filename=name,
            filepath=path,
        )

    return None


def is_versioned_migration(target: str | pathlib.Path) -> bool:
    """Return True if the target matches a versioned migration pattern (V<version>__<desc>.sql)."""
    name = pathlib.Path(target).name
    return bool(VERSIONED_RE.match(name))


def is_undo_migration(target: str | pathlib.Path) -> bool:
    """Return True if the target matches an undo migration pattern (U<version>__<desc>.sql)."""
    name = pathlib.Path(target).name
    return bool(UNDO_RE.match(name))


def is_repeatable_migration(target: str | pathlib.Path) -> bool:
    """Return True if the target matches a repeatable migration pattern (R__<desc>.sql)."""
    name = pathlib.Path(target).name
    return bool(REPEATABLE_RE.match(name))


def is_callback_migration(target: str | pathlib.Path) -> bool:
    """Return True if the target matches a callback script pattern."""
    info = parse_migration_filename(target)
    return info is not None and info.migration_type == "callback"


def extract_version(target: str | pathlib.Path) -> Optional[str]:
    """Extract version string from a versioned or undo migration filename."""
    info = parse_migration_filename(target)
    return info.version if info else None


def is_single_underscore_migration(target: str | pathlib.Path) -> bool:
    """Return True if filename uses a single '_' between version number and description instead of '__'."""
    name = pathlib.Path(target).name
    return bool(SINGLE_UNDERSCORE_VERSIONED_RE.match(name) or SINGLE_UNDERSCORE_UNDO_RE.match(name))


def detect_single_underscore_migrations(
    scripts_dir_or_files: pathlib.Path | Iterable[pathlib.Path],
) -> List[pathlib.Path]:
    """Scans scripts_dir or inspects a collection of file paths and returns a list of migration
    file paths that use a single '_' separator between version number and description instead of double '__'.
    """
    if isinstance(scripts_dir_or_files, pathlib.Path):
        if not scripts_dir_or_files.exists():
            return []
        files: Iterable[pathlib.Path] = sorted(scripts_dir_or_files.rglob("*.sql"))
    else:
        files = scripts_dir_or_files

    malformed: List[pathlib.Path] = []
    for filepath in files:
        if is_single_underscore_migration(filepath.name):
            malformed.append(filepath)
    return malformed


def validate_migration_filename(target: str | pathlib.Path) -> FlywayMigrationInfo:
    """Validate a migration filename and return FlywayMigrationInfo.

    :raises ValueError: If filename does not match any valid Flyway pattern.
    """
    if is_single_underscore_migration(target):
        name = pathlib.Path(target).name
        raise ValueError(
            f"Invalid Flyway migration filename: '{name}' uses a single '_' separator. "
            "Migrations must use double '__' separating version and name (e.g. V1.0__description.sql) in order for Alembic to run them."
        )

    info = parse_migration_filename(target)
    if not info:
        name = pathlib.Path(target).name
        raise ValueError(
            f"Invalid Flyway migration filename: '{name}'. "
            "Expected formats: V<ver>__<desc>.sql, U<ver>__<desc>.sql, R__<desc>.sql, or <callback>.sql"
        )
    return info



def version_key(version_str: str) -> Tuple[int, ...]:
    """Turn a dotted revision string into a tuple of integers for numeric version sorting.

    Handles standard versions (e.g. "1.0"), 12-digit timestamps ("202408160101.1"),
    and pre-merge placeholder versions ("999999999999.1").
    """
    parts = []
    for part in version_str.split("."):
        try:
            parts.append(int(part))
        except ValueError:
            # Fallback for non-numeric components if any exist
            parts.append(part) # type: ignore
    return tuple(parts)


def list_pending_migrations(
    scripts_dir: pathlib.Path,
    current_revision: Optional[str],
    sql_files: Optional[Iterable[pathlib.Path]] = None,
) -> List[Tuple[str, str]]:
    """Discover versioned migration files in scripts_dir and return unapplied (version, filename) pairs.

    Uses version_key for numeric sorting and filters against current_revision.
    """
    if sql_files is None:
        if not scripts_dir.exists():
            return []
        files: Iterable[pathlib.Path] = sorted(scripts_dir.rglob("*.sql"))
    else:
        files = sql_files

    upgrades: Dict[str, pathlib.Path] = {}
    for filepath in files:
        info = parse_migration_filename(filepath)
        if info and info.migration_type == "versioned" and info.version:
            upgrades[info.version] = filepath

    if not upgrades:
        return []

    sorted_versions = sorted(upgrades.keys(), key=version_key)
    pending_versions: List[str] = []

    if not current_revision or current_revision.strip().lower() in ("none", "null", "base", "''", '""'):
        pending_versions = sorted_versions
    else:
        try:
            cur_key = version_key(current_revision)
            pending_versions = [v for v in sorted_versions if version_key(v) > cur_key]
        except Exception:
            # Fallback if comparison encounters unexpected revision formats
            if current_revision in sorted_versions:
                idx = sorted_versions.index(current_revision)
                pending_versions = sorted_versions[idx + 1 :]
            else:
                pending_versions = sorted_versions

    return [(v, upgrades[v].name) for v in pending_versions]


def list_pending_versions(scripts_dir: pathlib.Path, current_revision: Optional[str]) -> List[str]:
    """Discover versioned migration files in scripts_dir and return unapplied version numbers."""
    return [v for v, _ in list_pending_migrations(scripts_dir, current_revision)]


def main() -> int:
    """CLI utility for shell integration (e.g., used by alembic.sh status)."""
    parser = argparse.ArgumentParser(description="Flyway Migration Name Validator CLI")
    subparsers = parser.add_subparsers(dest="command")

    pending_parser = subparsers.add_parser("list-pending", help="List unapplied versioned migrations")
    pending_parser.add_argument("--scripts-dir", required=True, type=pathlib.Path, help="Path to scripts directory")
    pending_parser.add_argument("--current", default="", help="Current revision applied in DB")
    pending_parser.add_argument("--versions-only", action="store_true", help="Print version numbers only without filenames")

    validate_parser = subparsers.add_parser("validate", help="Validate a filename")
    validate_parser.add_argument("filename", help="Filename or path to validate")

    args = parser.parse_args()

    if args.command == "list-pending":
        cur_rev = args.current.strip() if args.current else None
        sql_files = sorted(args.scripts_dir.rglob("*.sql")) if args.scripts_dir.exists() else []
        malformed = detect_single_underscore_migrations(sql_files)
        if malformed:
            file_names = ", ".join(f.name for f in malformed)
            sys.stderr.write(
                f"🙅‍♀️ WARNING: Found {len(malformed)} migration file(s) with a single '_' separator instead of '__': [{file_names}]. "
                "These files MUST be renamed to use double '__' (e.g. V<ver>__<name>.sql) in order for Alembic to run them.\n"
            )

        pending = list_pending_migrations(args.scripts_dir, cur_rev, sql_files=sql_files)
        for version, filename in pending:
            if args.versions_only:
                print(version)
            else:
                print(f"{version} - {filename}")
        return 0

    elif args.command == "validate":
        try:
            info = validate_migration_filename(args.filename)
            print(f"Valid {info.migration_type}: version={info.version}, desc={info.description}")
            return 0
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())

