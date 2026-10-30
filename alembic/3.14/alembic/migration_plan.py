"""Builds a single, globally ordered migration execution plan across all schemas.

Background (issue #787)
-----------------------
Oracle schemas are logical ownership namespaces, but database changes happen in
chronological order. Running migrations schema-by-schema therefore breaks as
soon as cross-schema dependencies exist: if ``THE`` depends on ``CONSEP`` and
``CONSEP`` depends back on ``THE``, no schema-at-a-time ordering can satisfy
both.

This module produces a flat, ordered list of execution *segments* spanning every
schema. A segment is a contiguous run of migrations belonging to one schema, and
is executed by handing it to ``alembic.sh --schema <s> upgrade-to <version>``.

Two layers, two very different ordering rules
---------------------------------------------
1. **Baseline** - the frozen extraction of the production structure. Every
   schema numbers its object-type folders starting at major 1, so a numeric sort
   across schemas is meaningless here. The order is instead *declared* in
   ``baseline_order.json``.

2. **Timestamped** - everything merged since. ``merge.yml`` stamps every V/U
   file in a merged PR with one shared 12-digit major, preserving the author's
   minors. Those minors are what encode cross-schema intent, so this layer is
   ordered by a plain global numeric sort.

The layers compose without any renumbering: every baseline major is <= 16 and
every timestamp major has at least 12 digits, so the entire baseline necessarily
sorts first.

Why per-schema version tables still work
----------------------------------------
A global order is a total order, so each schema's own migrations form a strictly
increasing *subsequence* of it. Alembic tracks a per-schema high-water mark, and
a high-water mark remains correct over an increasing subsequence. Interleaving
across schemas therefore needs no change to the tracking tables and no change to
``env.py``.

This module deliberately performs no database access and spawns no
subprocesses, so the ordering logic is unit-testable against a directory of
empty files.
"""

import argparse
import json
import logging
import pathlib
import sys
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

try:
    import flyway_migration_name_validator as flyway_validator
except ImportError:  # pragma: no cover - import shim mirrors env.py
    from . import flyway_migration_name_validator as flyway_validator

logger = logging.getLogger("alembic.migration_plan")

# Smallest 12-digit value. merge.yml stamps merged migrations with a
# YYYYMMDDHHMM major, so anything at or above this is a timestamped migration
# (or a developer placeholder such as V999999999999 used to force "run last").
# Anything below it that the baseline manifest does not claim is a numbering
# mistake rather than a timestamp, and is reported as an error.
TIMESTAMP_MIN_MAJOR = 100_000_000_000

DEFAULT_MANIFEST = pathlib.Path(__file__).resolve().parent / "baseline_order.json"
DEFAULT_SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent.parent / "scripts"

LAYER_BASELINE = "baseline"
LAYER_TIMESTAMP = "timestamp"


class MigrationPlanError(RuntimeError):
    """Raised when a correct global ordering cannot be determined."""


@dataclass(frozen=True)
class MigrationFile:
    """A single discovered migration script."""

    schema: str
    version: str
    path: pathlib.Path
    kind: str  # "V" or "U"

    @property
    def version_key(self) -> Tuple[int, ...]:
        return version_key(self.version)

    @property
    def major(self) -> int:
        return self.version_key[0]


@dataclass(frozen=True)
class BaselineSegment:
    """One declared entry from baseline_order.json."""

    schema: str
    oracle_user: str
    through_major: int
    grants: bool


@dataclass(frozen=True)
class PlanSegment:
    """A contiguous run of migrations in one schema, executed as one command.

    ``version`` is the exact on-disk version string of the last migration in the
    run, suitable for ``alembic.sh upgrade-to``.
    """

    oracle_user: str
    schema: str
    version: str
    layer: str
    grants: bool = False

    def as_tsv(self) -> str:
        return f"{self.oracle_user}\t{self.schema}\t{self.version}\t{self.layer}"

    def as_dict(self) -> Dict[str, object]:
        return {
            "oracle_user": self.oracle_user,
            "schema": self.schema,
            "version": self.version,
            "layer": self.layer,
            "grants": self.grants,
        }


def version_key(revision: str) -> Tuple[int, ...]:
    """Turn a dotted revision string into a tuple of ints for numeric sorting.

    Mirrors ``AlembicUtils.version_key`` in env.py so that the plan and the
    migration engine agree on ordering.

    :param revision: a revision string such as "15.00096" or "202610061136.11"
    :return: tuple of integers safe to compare and sort
    """
    try:
        return tuple(int(part) for part in revision.split("."))
    except ValueError as exc:
        raise MigrationPlanError(f"Un-parseable migration version {revision!r}") from exc


def load_manifest(manifest_path: pathlib.Path = DEFAULT_MANIFEST) -> List[BaselineSegment]:
    """Load the declared baseline execution order.

    :param manifest_path: path to baseline_order.json
    :return: segments in declared execution order
    """
    if not manifest_path.exists():
        raise MigrationPlanError(f"Baseline order manifest not found: {manifest_path}")

    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw_segments = data.get("segments")
    if not raw_segments:
        raise MigrationPlanError(f"Baseline order manifest has no segments: {manifest_path}")

    segments: List[BaselineSegment] = []
    for entry in raw_segments:
        try:
            segments.append(
                BaselineSegment(
                    schema=str(entry["schema"]).upper(),
                    oracle_user=str(entry["oracle_user"]).upper(),
                    through_major=int(entry["through_major"]),
                    grants=bool(entry.get("grants", False)),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise MigrationPlanError(
                f"Malformed segment in {manifest_path}: {entry!r}"
            ) from exc
    return segments


def discover_migrations(scripts_dir: pathlib.Path = DEFAULT_SCRIPTS_DIR) -> List[MigrationFile]:
    """Find every versioned (V) and undo (U) migration beneath ``scripts_dir``.

    The schema is taken from the first path component under ``scripts_dir``,
    which is the same convention ``alembic.sh --schema`` uses.

    :param scripts_dir: the repository ``scripts`` directory
    :return: discovered migrations, unordered
    """
    if not scripts_dir.exists():
        raise MigrationPlanError(f"Scripts directory does not exist: {scripts_dir}")

    discovered: List[MigrationFile] = []
    for path in scripts_dir.rglob("*.sql"):
        relative = path.relative_to(scripts_dir)
        if len(relative.parts) < 2:
            continue  # schema-root loose file, not a schema-owned migration

        schema = relative.parts[0].upper()

        versioned = flyway_validator.VERSIONED_RE.match(path.name)
        if versioned:
            discovered.append(
                MigrationFile(schema=schema, version=versioned.group(1), path=path, kind="V")
            )
            continue

        undo = flyway_validator.UNDO_RE.match(path.name)
        if undo:
            discovered.append(
                MigrationFile(schema=schema, version=undo.group(1), path=path, kind="U")
            )

    return discovered


def _find_collisions(
    migrations: Iterable[MigrationFile],
    scope: str,
) -> List[str]:
    """Report migrations of the same kind that share a version within ``scope``.

    ``scope`` is either "global" (compare across all schemas) or "schema"
    (compare only within each schema).

    V and U files intentionally share a version with each other (``V12.1`` pairs
    with ``U12.1``), so the two kinds are always checked independently.
    """
    collisions: List[str] = []

    for kind in ("V", "U"):
        seen: Dict[Tuple[object, ...], MigrationFile] = {}
        candidates = sorted(
            (m for m in migrations if m.kind == kind),
            key=lambda m: (m.version_key, m.schema, m.path.name),
        )
        for migration in candidates:
            key: Tuple[object, ...] = (
                (migration.version_key,)
                if scope == "global"
                else (migration.schema, migration.version_key)
            )
            previous = seen.get(key)
            if previous is not None:
                collisions.append(
                    f"  - {kind}{migration.version} is used twice:\n"
                    f"      {previous.path}\n"
                    f"      {migration.path}"
                )
                continue
            seen[key] = migration

    return collisions


def assert_version_uniqueness(
    manifest: Sequence[BaselineSegment],
    migrations: Sequence[MigrationFile],
) -> None:
    """Fail when duplicate versions would make the execution order ambiguous.

    The two layers are held to deliberately different standards, because they
    are ordered by different mechanisms:

    * **Timestamped / pending migrations are ordered by a global numeric sort**,
      so a version shared across two schemas is a genuine ambiguity - the files
      tie, and their relative order degrades into an arbitrary tie-break rather
      than a stated intent. Checked globally.

    * **Baseline migrations are ordered by the manifest, not by sorting.** Every
      schema's extraction numbers its object-type folders from major 1, so
      ``THE/SEQUENCES/V1.00001`` and ``CONSEP/SEQUENCES/V1.00001`` both exist by
      construction and are entirely unambiguous: the manifest states which runs
      first. Only within-schema duplicates are errors here, matching what
      ``MigrationFiles.discover_sql_migrations`` already enforces at run time.

    Making the baseline globally unique would require the renumbering described
    in issue #787 Phase 1, which is deliberately deferred.

    :param manifest: declared baseline order
    :param migrations: discovered migrations
    :raises MigrationPlanError: when a duplicate version is found
    """
    claimed = _claimed_majors(manifest)

    baseline = [m for m in migrations if (m.schema, m.major) in claimed]
    pending = [m for m in migrations if (m.schema, m.major) not in claimed]

    errors: List[str] = []

    schema_collisions = _find_collisions(baseline, scope="schema")
    if schema_collisions:
        errors.append(
            "Baseline migrations must have a unique version within their own schema:\n"
            + "\n".join(schema_collisions)
        )

    global_collisions = _find_collisions(pending, scope="global")
    if global_collisions:
        errors.append(
            "Timestamped migrations must have a globally unique version across all\n"
            "schemas, because they are ordered by a single global numeric sort:\n"
            + "\n".join(global_collisions)
        )

    if errors:
        raise MigrationPlanError(
            "Migration version collision detected.\n\n" + "\n\n".join(errors)
        )


def _claimed_majors(manifest: Sequence[BaselineSegment]) -> Dict[Tuple[str, int], BaselineSegment]:
    """Map every ``(schema, major)`` the manifest claims to its owning segment.

    A segment claims the majors in ``(previous through_major for that schema,
    through_major]``, so consecutive segments partition a schema's baseline.
    """
    claimed: Dict[Tuple[str, int], BaselineSegment] = {}
    previous_through: Dict[str, int] = {}

    for segment in manifest:
        start = previous_through.get(segment.schema, 0) + 1
        if segment.through_major < start:
            raise MigrationPlanError(
                f"Baseline manifest segment for {segment.schema} declares "
                f"through_major={segment.through_major}, which does not advance past "
                f"the previous segment ({start - 1}). Segments must be ordered and increasing."
            )
        for major in range(start, segment.through_major + 1):
            claimed[(segment.schema, major)] = segment
        previous_through[segment.schema] = segment.through_major

    return claimed


def build_baseline_plan(
    manifest: Sequence[BaselineSegment],
    migrations: Sequence[MigrationFile],
    include_grants: bool = True,
) -> List[PlanSegment]:
    """Resolve the declared baseline order into executable segments.

    Each manifest segment is resolved to the highest actual version among the
    majors it claims, so the driver only ever needs ``upgrade-to``.

    :param manifest: declared baseline order
    :param migrations: discovered migrations
    :param include_grants: when False, grant segments are omitted (--no-grants)
    :return: executable segments in declared order
    """
    claimed = _claimed_majors(manifest)
    versioned = [m for m in migrations if m.kind == "V"]

    by_segment: Dict[int, List[MigrationFile]] = {}
    for migration in versioned:
        segment = claimed.get((migration.schema, migration.major))
        if segment is None:
            continue
        by_segment.setdefault(id(segment), []).append(migration)

    plan: List[PlanSegment] = []
    for segment in manifest:
        members = by_segment.get(id(segment), [])
        if not members:
            logger.warning(
                "Baseline manifest segment %s through major %s claims no migration files. "
                "The manifest may be stale.",
                segment.schema,
                segment.through_major,
            )
            continue
        if segment.grants and not include_grants:
            continue

        last = max(members, key=lambda m: m.version_key)
        plan.append(
            PlanSegment(
                oracle_user=segment.oracle_user,
                schema=segment.schema,
                version=last.version,
                layer=LAYER_BASELINE,
                grants=segment.grants,
            )
        )

    return plan


def _collapse(
    migrations: Sequence[MigrationFile],
    users: Dict[str, str],
) -> List[PlanSegment]:
    """Sort migrations globally and collapse same-schema runs into segments.

    The sort is by numeric version with the schema name as a deterministic
    tie-break, so the plan is reproducible. Consecutive migrations in the same
    schema collapse into a single segment, because ``upgrade-to <last>`` applies
    every intervening migration in that schema.
    """
    ordered = sorted(migrations, key=lambda m: (m.version_key, m.schema))

    plan: List[PlanSegment] = []
    for migration in ordered:
        if plan and plan[-1].schema == migration.schema:
            plan[-1] = PlanSegment(
                oracle_user=plan[-1].oracle_user,
                schema=plan[-1].schema,
                version=migration.version,
                layer=LAYER_TIMESTAMP,
            )
            continue
        plan.append(
            PlanSegment(
                oracle_user=users.get(migration.schema, migration.schema),
                schema=migration.schema,
                version=migration.version,
                layer=LAYER_TIMESTAMP,
            )
        )
    return plan


def find_unclaimed_low_majors(
    manifest: Sequence[BaselineSegment],
    migrations: Sequence[MigrationFile],
) -> List[MigrationFile]:
    """Return versioned migrations below the timestamp range that no segment claims.

    Such a file is ordered by its literal number, so it lands after the baseline
    but before every merged timestamped migration. That placement is legal and
    the plan handles it, but it has a consequence worth surfacing: on any
    database already past that version - which includes every PR clone, since a
    clone inherits the baseline's high-water mark - Alembic skips it. The
    migration is neither applied nor reported, so a PR containing one can pass
    validation without its SQL ever executing.

    This is reported as a warning rather than an error. The repository's
    documented convention (``V999999999999``) sorts above every real timestamp
    precisely so that new work *does* execute during validation, but migrations
    are renumbered to a real timestamp by ``merge.yml`` on merge, so a
    non-conforming major still runs correctly once merged.

    :param manifest: declared baseline order
    :param migrations: discovered migrations
    :return: unclaimed sub-timestamp migrations, ordered for display
    """
    claimed = _claimed_majors(manifest)

    unclaimed = [
        migration
        for migration in migrations
        if migration.kind == "V"
        and (migration.schema, migration.major) not in claimed
        and migration.major < TIMESTAMP_MIN_MAJOR
    ]
    return sorted(unclaimed, key=lambda m: (m.schema, m.version_key))


def _pending_migrations(
    manifest: Sequence[BaselineSegment],
    migrations: Sequence[MigrationFile],
) -> List[MigrationFile]:
    """Return the versioned migrations the baseline manifest does not claim.

    Migrations numbered below the timestamp range are included rather than
    rejected; they simply sort where their number places them. See
    :func:`find_unclaimed_low_majors` for why they are also warned about.
    """
    claimed = _claimed_majors(manifest)

    pending = [
        migration
        for migration in migrations
        if migration.kind == "V" and (migration.schema, migration.major) not in claimed
    ]

    unclaimed = find_unclaimed_low_majors(manifest, migrations)
    if unclaimed:
        details = "\n".join(
            f"      - {m.path.name} in {m.path.parent} (major {m.major})"
            for m in unclaimed
        )
        logger.warning(
            "%d migration(s) use a major version below %d that the baseline manifest "
            "does not claim:\n%s\n"
            "    These are included in the plan and will run on a database built from "
            "scratch, but any database already past that version - including every PR "
            "clone - will skip them silently. Use V999999999999 for new work so it "
            "actually executes during validation.",
            len(unclaimed),
            TIMESTAMP_MIN_MAJOR,
            details,
        )

    return pending


def build_timestamp_plan(
    manifest: Sequence[BaselineSegment],
    migrations: Sequence[MigrationFile],
) -> List[PlanSegment]:
    """Globally order every migration the baseline manifest does not claim.

    :param manifest: declared baseline order, used for schema -> user mapping
    :param migrations: discovered migrations
    :return: executable segments in global order
    """
    users = {segment.schema: segment.oracle_user for segment in manifest}
    return _collapse(_pending_migrations(manifest, migrations), users)


def build_applied_plan(
    manifest: Sequence[BaselineSegment],
    migrations: Sequence[MigrationFile],
    floors: Dict[str, Optional[str]],
    ceilings: Dict[str, Optional[str]],
) -> List[PlanSegment]:
    """Plan covering only the migrations applied between ``floors`` and ``ceilings``.

    Used by rollback verification to reconstruct, in exact global order, what a
    change set actually applied - so it can then be unwound in exact reverse
    order via :func:`build_downgrade_plan`.

    :param floors: schema -> revision in place before the change set ran.
        None means the schema had no migrations applied at all.
    :param ceilings: schema -> revision in place after the change set ran.
        None means nothing is applied in that schema, so nothing to unwind.
    :return: executable segments covering only the applied migrations
    """
    users = {segment.schema: segment.oracle_user for segment in manifest}

    selected: List[MigrationFile] = []
    for migration in _pending_migrations(manifest, migrations):
        ceiling = ceilings.get(migration.schema)
        if not ceiling:
            continue
        if migration.version_key > version_key(ceiling):
            continue
        floor = floors.get(migration.schema)
        if floor and migration.version_key <= version_key(floor):
            continue
        selected.append(migration)

    return _collapse(selected, users)


def build_plan(
    layer: str = "all",
    scripts_dir: pathlib.Path = DEFAULT_SCRIPTS_DIR,
    manifest_path: pathlib.Path = DEFAULT_MANIFEST,
    include_grants: bool = True,
) -> List[PlanSegment]:
    """Build the execution plan for the requested layer(s).

    :param layer: "baseline", "timestamps" or "all"
    :param scripts_dir: the repository ``scripts`` directory
    :param manifest_path: path to baseline_order.json
    :param include_grants: when False, baseline grant segments are omitted
    :return: executable segments in execution order
    """
    manifest = load_manifest(manifest_path)
    migrations = discover_migrations(scripts_dir)
    assert_version_uniqueness(manifest, migrations)

    plan: List[PlanSegment] = []
    if layer in ("baseline", "all"):
        plan.extend(build_baseline_plan(manifest, migrations, include_grants=include_grants))
    if layer in ("timestamps", "all"):
        plan.extend(build_timestamp_plan(manifest, migrations))
    return plan


def build_downgrade_plan(
    segments: Sequence[PlanSegment],
    floors: Optional[Dict[str, Optional[str]]] = None,
) -> List[Tuple[PlanSegment, str]]:
    """Invert a forward plan into an ordered list of downgrade steps.

    Rolling back an interleaved change set schema-by-schema is wrong: undoing all
    of ``THE`` before ``CONSEP`` tears out objects that ``CONSEP`` still
    references. The segments must be unwound in exact reverse order.

    Each step pairs a segment with the version to downgrade *to* - its floor.
    ``alembic.sh downgrade <ver>`` undoes everything above ``<ver>`` and keeps
    ``<ver>`` itself, so the floor is the previous target for that same schema,
    or the schema's pre-change revision when the segment is that schema's first.

    :param segments: the forward plan, in execution order
    :param floors: schema -> revision in place before the forward plan ran.
        A missing or None entry means roll that schema back to ``base``.
    :return: (segment, downgrade_target) pairs in reverse execution order
    """
    floors = floors or {}

    previous_for_schema: Dict[str, str] = {}
    targets: List[str] = []

    for segment in segments:
        floor = previous_for_schema.get(segment.schema)
        if floor is None:
            floor = floors.get(segment.schema) or "base"
        targets.append(floor)
        previous_for_schema[segment.schema] = segment.version

    return list(reversed(list(zip(segments, targets))))


def render(segments: Sequence[PlanSegment], output_format: str) -> str:
    """Render a plan as TSV (for the bash drivers) or JSON (for tooling)."""
    if output_format == "json":
        return json.dumps([segment.as_dict() for segment in segments], indent=2)
    return "\n".join(segment.as_tsv() for segment in segments)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="migration_plan",
        description="Emit a globally ordered, cross-schema migration execution plan.",
    )
    parser.add_argument(
        "--layer",
        choices=["baseline", "timestamps", "all"],
        default="all",
        help="which layer(s) to emit (default: all)",
    )
    parser.add_argument(
        "--format",
        dest="output_format",
        choices=["tsv", "json"],
        default="tsv",
        help="output format (default: tsv, one segment per line)",
    )
    parser.add_argument(
        "--no-grants",
        action="store_true",
        help="omit baseline grant segments",
    )
    parser.add_argument(
        "--scripts-dir",
        type=pathlib.Path,
        default=DEFAULT_SCRIPTS_DIR,
        help=f"scripts directory to scan (default: {DEFAULT_SCRIPTS_DIR})",
    )
    parser.add_argument(
        "--manifest",
        type=pathlib.Path,
        default=DEFAULT_MANIFEST,
        help=f"baseline order manifest (default: {DEFAULT_MANIFEST})",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s", stream=sys.stderr)
    args = parse_args(argv)

    try:
        plan = build_plan(
            layer=args.layer,
            scripts_dir=args.scripts_dir,
            manifest_path=args.manifest,
            include_grants=not args.no_grants,
        )
    except MigrationPlanError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1

    rendered = render(plan, args.output_format)
    if rendered:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
