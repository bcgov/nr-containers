#!/usr/bin/env python3
"""
PR Rollback and Object-Count Verification Script for Oracle Clone Validation (Scenario B / #652).

Executes the 6 required verification steps against an Oracle clone PDB:
1. Count objects before PR migrations & record initial schema revisions.
2. Run PR migrations (run_all_migrations.sh & run_timestamp_migrations.sh).
3. Count objects after PR migrations.
4. Run U rollbacks (mandatory — missing U files or failed rollback fails the PR).
5. Count objects again after rollbacks.
6. Compare before vs after-rollback counts; fail if before != after-rollback.
"""

import os
import sys
import subprocess
import pathlib
import re
from typing import Dict, Tuple, List, Optional
import oracledb

try:
    import flyway_migration_name_validator as flyway_validator
except ImportError:
    from . import flyway_migration_name_validator as flyway_validator

try:
    import migration_plan
except ImportError:
    from . import migration_plan  # type: ignore[no-redef]

try:
    from env import load_flyway_properties
except ImportError:
    from .env import load_flyway_properties  # type: ignore[no-redef]


def get_managed_schemas() -> List[str]:
    """Every schema folder under scripts/ that the baseline manifest knows about.

    Previously this was a hardcoded four-entry list that omitted APP_DBA,
    APP_FDSUTIL, APP_FTA, APP_RESPROJ and APP_RESULTS, so migrations applied to
    those schemas were never considered for rollback.
    """
    manifest = migration_plan.load_manifest()
    seen: List[str] = []
    for segment in manifest:
        if segment.schema not in seen:
            seen.append(segment.schema)
    return seen


SCHEMAS = get_managed_schemas()


def get_db_connection() -> oracledb.Connection:
    """Connect to Oracle database using environment variables. Always prefers SYSDBA when SYS password available."""
    host = os.getenv("ORACLE_HOST", "localhost")
    port = int(os.getenv("ORACLE_PORT", "1525"))
    service = os.getenv("ORACLE_SERVICE", "DBDOCK_01")
    sys_password = os.getenv("ORACLE_SYS_PASSWORD")
    user = os.getenv("ORACLE_USER", "SYS")
    dsn = oracledb.makedsn(host, port, service_name=service)

    if sys_password:
        return oracledb.connect(user="SYS", password=sys_password, dsn=dsn, mode=oracledb.SYSDBA)
    elif user.upper() == "SYS":
        password = os.getenv("ORACLE_PASSWORD", "default")
        return oracledb.connect(user="SYS", password=password, dsn=dsn, mode=oracledb.SYSDBA)
    else:
        password = os.getenv("ORACLE_PASSWORD", "default")
        return oracledb.connect(user=user, password=password, dsn=dsn)


def count_db_objects(conn: oracledb.Connection) -> Tuple[int, Dict[Tuple[str, str], int]]:
    """
    Count database objects in the PDB, excluding Oracle internal system schemas.
    Returns (total_count, detailed_map_by_owner_and_type).
    """
    sql = """
        SELECT owner, object_type, COUNT(*)
        FROM dba_objects
        WHERE owner NOT IN ( SELECT username FROM dba_users WHERE oracle_maintained = 'Y' )
        AND owner NOT LIKE 'C##%'
        GROUP BY owner, object_type
        ORDER BY owner, object_type
    """
    cursor = conn.cursor()
    cursor.execute(sql)
    detailed_map: Dict[Tuple[str, str], int] = {}
    total_count = 0
    for owner, obj_type, cnt in cursor.fetchall():
        detailed_map[(owner, obj_type)] = cnt
        total_count += cnt
    cursor.close()
    return total_count, detailed_map


def get_version_table_info(schema: str) -> Tuple[str, str]:
    """Return (table_schema, table_name) for a given schema's Alembic version table.

    Resolved from the schema's Flyway properties file via the same helper env.py
    uses, so the two cannot drift. They previously had drifted: this function
    reported ``THE.ALEMBIC_VERSION_SQL`` while the table env.py actually writes
    is ``ALEMBIC.THE_ALEMBIC_VERSION_SQL``. Every lookup therefore raised
    ORA-00942, was swallowed below, and reported "no revision" - which silently
    disabled both the rollback execution and the mandatory U-script check.
    """
    schema_upper = schema.upper()
    properties = load_flyway_properties(schema_upper)

    table_schema = properties.get("flyway.defaultschema", "ALEMBIC")
    table_name = properties.get("flyway.table", f"{schema_upper}_ALEMBIC_VERSION_SQL")
    return (table_schema.upper(), table_name.upper())


def get_schema_revision_from_db(conn: oracledb.Connection, schema: str) -> Optional[str]:
    """Query the current (highest) Alembic revision for a schema from the database.

    Alembic treats the current revision as a high-water mark, so the answer is
    the numerically greatest applied version - not whichever row Oracle happens
    to return first, which is what this used to do.

    A missing version table (ORA-00942) is a legitimate state: the schema has
    never been migrated, so the revision is genuinely None. Every other error is
    re-raised. Returning None for, say, a transient connection drop or a
    permission problem would make the before and after revisions compare equal,
    which silently skips both the mandatory U-script check and the rollback
    itself - the exact fail-open this function exists to prevent.

    :raises RuntimeError: if the version table cannot be read for any reason
        other than it not existing.
    """
    cursor = conn.cursor()
    table_schema, table_name = get_version_table_info(schema)
    full_table = f"{table_schema}.{table_name}"
    try:
        cursor.execute(f"SELECT version_num FROM {full_table}")
        rows = cursor.fetchall()
    except oracledb.DatabaseError as exc:
        error = exc.args[0] if exc.args else None
        if getattr(error, "code", None) == 942:
            print(f"  ({full_table} does not exist yet; {schema} has no applied revisions)")
            return None
        raise RuntimeError(
            f"Could not read the Alembic version table {full_table} for schema {schema}: {exc}. "
            "Rollback verification cannot continue safely without this schema's current "
            "revision, because an unreadable table makes the before and after revisions "
            "appear equal and would silently skip both the mandatory U-script check and "
            "the rollback."
        ) from exc
    finally:
        cursor.close()

    versions = [str(row[0]).strip() for row in rows if row and row[0]]
    if not versions:
        return None
    return max(versions, key=flyway_validator.version_key)


def get_schema_revisions(conn: oracledb.Connection) -> Dict[str, Optional[str]]:
    """Get current revisions for all application schemas."""
    revisions = {}
    for schema in SCHEMAS:
        revisions[schema] = get_schema_revision_from_db(conn, schema)
    return revisions


def read_schema_revisions_or_exit(
    conn: oracledb.Connection,
    stage: str,
) -> Dict[str, Optional[str]]:
    """Read every schema's revision, failing the run if any cannot be read.

    Fails closed on purpose: continuing with incomplete revision data would
    silently skip rollback verification rather than report a problem.
    """
    try:
        return get_schema_revisions(conn)
    except RuntimeError as exc:
        print(f"::error::Could not determine schema revisions {stage}: {exc}", file=sys.stderr)
        conn.close()
        sys.exit(1)


def get_scripts_dir() -> pathlib.Path:
    """Locate scripts directory (supports container /app/scripts and local repo root)."""
    candidates = [
        pathlib.Path("/app/scripts"),
        pathlib.Path("./scripts"),
        pathlib.Path("../scripts"),
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_dir():
            return candidate.resolve()
    return pathlib.Path("./scripts").resolve()


def verify_u_scripts_for_applied_revisions(
    scripts_dir: pathlib.Path,
    before_revisions: Dict[str, Optional[str]],
    after_revisions: Dict[str, Optional[str]],
) -> List[str]:
    """
    Verify that every V migration file applied during the PR has a corresponding U rollback script.
    Returns list of missing U script error messages.
    """
    missing_u: List[str] = []
    version_re = flyway_validator.VERSIONED_RE

    for schema in SCHEMAS:
        before_rev = before_revisions.get(schema)
        after_rev = after_revisions.get(schema)

        if before_rev == after_rev:
            continue

        schema_dir = scripts_dir / schema
        if not schema_dir.exists():
            continue

        # Find all V migrations in this schema
        schema_v_files: List[Tuple[str, pathlib.Path]] = []
        for path in sorted(schema_dir.rglob("*.sql")):
            m = version_re.match(path.name)
            if m:
                ver = m.group(1)
                schema_v_files.append((ver, path))

        def parse_version(v_str: str) -> Tuple[int, ...]:
            return flyway_validator.version_key(v_str)

        before_ver = parse_version(before_rev) if before_rev else ()
        after_ver = parse_version(after_rev) if after_rev else ()


        for ver, v_path in schema_v_files:
            v_num = parse_version(ver)
            if (not before_ver or v_num > before_ver) and (after_ver and v_num <= after_ver):
                m = version_re.match(v_path.name)
                if m:
                    ver_str = m.group(1)
                    desc_str = m.group(2)
                    expected_u = f"U{ver_str}__{desc_str}.sql"
                    u_path = v_path.parent / expected_u
                    if not u_path.exists():
                        missing_u.append(
                            f"Missing mandatory rollback script '{expected_u}' for applied migration '{v_path.name}' under {v_path.parent}"
                        )

    return missing_u


def run_command(
    cmd: List[str],
    check: bool = True,
    env: Optional[Dict[str, str]] = None,
) -> subprocess.CompletedProcess:
    """Run a shell command with optional environment overrides and print output."""
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    print(f"▶ Running: {' '.join(cmd)}")
    res = subprocess.run(cmd, capture_output=True, text=True, env=full_env)
    if res.stdout:
        print(res.stdout)
    if res.stderr:
        print(res.stderr, file=sys.stderr)
    if check and res.returncode != 0:
        raise RuntimeError(f"Command failed with exit code {res.returncode}: {' '.join(cmd)}")
    return res


def get_alembic_executable() -> str:
    """Find alembic.sh executable location."""
    candidates = [
        pathlib.Path("/app/alembic.sh"),
        pathlib.Path("./alembic.sh"),
        pathlib.Path("../alembic.sh"),
    ]
    for c in candidates:
        if c.exists():
            return str(c.resolve())
    return "./alembic.sh"


def format_object_deltas(
    before_map: Dict[Tuple[str, str], int],
    after_map: Dict[Tuple[str, str], int],
) -> str:
    """Format difference between before and after object maps."""
    all_keys = sorted(set(before_map.keys()) | set(after_map.keys()))
    lines = []
    lines.append(f"{'OWNER':<20} {'OBJECT_TYPE':<25} {'BEFORE':<10} {'AFTER_ROLLBACK':<15} {'DELTA':<10}")
    lines.append("-" * 80)
    for owner, obj_type in all_keys:
        b_cnt = before_map.get((owner, obj_type), 0)
        a_cnt = after_map.get((owner, obj_type), 0)
        delta = a_cnt - b_cnt
        if delta != 0:
            lines.append(f"{owner:<20} {obj_type:<25} {b_cnt:<10} {a_cnt:<15} {delta:+d}")
    return "\n".join(lines)


def main():
    """Main verification routine implementing the 6 required steps."""
    print("==========================================================================")
    print("Scenario B: Oracle Clone PR Rollback & Object-Count Verification (#652)")
    print("==========================================================================")

    print("\nConnecting to Oracle PDB...")
    try:
        conn = get_db_connection()
    except Exception as e:
        print(f"::error::Failed to connect to Oracle database: {e}", file=sys.stderr)
        sys.exit(1)

    print("\n--- Step 1: Count objects BEFORE PR migrations ---")
    before_count, before_map = count_db_objects(conn)
    before_revisions = read_schema_revisions_or_exit(conn, "before PR migrations")
    print(f"Before object count: {before_count}")
    print(f"Before schema revisions: {before_revisions}")

    print("\n--- Step 2: Running PR migrations against clone ---")
    run_all_script = "/app/run_all_migrations.sh" if os.path.exists("/app/run_all_migrations.sh") else "./run_all_migrations.sh"
    run_ts_script = "/app/run_timestamp_migrations.sh" if os.path.exists("/app/run_timestamp_migrations.sh") else "./run_timestamp_migrations.sh"

    try:
        print("▶ Running extracted schema migrations...")
        run_command(["/bin/bash", run_all_script])
        print("▶ Running timestamped migrations...")
        run_command(["/bin/bash", run_ts_script])
    except Exception as e:
        print(f"::error::PR migration execution failed: {e}", file=sys.stderr)
        conn.close()
        sys.exit(1)

    print("\n--- Step 3: Count objects AFTER PR migrations ---")
    after_mig_count, after_mig_map = count_db_objects(conn)
    after_mig_revisions = read_schema_revisions_or_exit(conn, "after PR migrations")
    print(f"After migration object count: {after_mig_count}")
    print(f"After migration schema revisions: {after_mig_revisions}")

    print("\n--- Step 4: Validate U rollbacks & execute rollbacks ---")
    scripts_dir = get_scripts_dir()
    missing_u = verify_u_scripts_for_applied_revisions(scripts_dir, before_revisions, after_mig_revisions)
    if missing_u:
        print("::error::Mandatory rollback scripts are missing for applied PR migrations:", file=sys.stderr)
        for msg in missing_u:
            print(f"::error::  - {msg}", file=sys.stderr)
        conn.close()
        sys.exit(1)
    print("✓ All applied PR migrations have matching U rollback scripts.")

    alembic_exe = get_alembic_executable()
    try:
        # Reconstruct, in exact global order, what this PR actually applied, then
        # unwind it in exact reverse order. Rolling back schema-by-schema (the
        # previous behaviour) tears out objects that a later schema still
        # references whenever a change set interleaves across schemas.
        applied = migration_plan.build_applied_plan(
            manifest=migration_plan.load_manifest(),
            migrations=migration_plan.discover_migrations(scripts_dir),
            floors=before_revisions,
            ceilings=after_mig_revisions,
        )
        steps = migration_plan.build_downgrade_plan(applied, floors=before_revisions)

        if not steps:
            print("No migrations were applied by this PR; nothing to roll back.")
        for index, (segment, target) in enumerate(steps, start=1):
            print(
                f"▶ [{index}/{len(steps)}] Rolling back {segment.schema} to "
                f"{target} as user {segment.oracle_user}..."
            )
            run_command(
                ["/bin/bash", alembic_exe, "--schema", segment.schema, "downgrade", target],
                env={"ORACLE_USER": segment.oracle_user},
            )
    except Exception as e:
        print(f"::error::Rollback execution failed: {e}", file=sys.stderr)
        conn.close()
        sys.exit(1)

    print("\n--- Step 5: Count objects AFTER rollbacks ---")
    after_rb_count, after_rb_map = count_db_objects(conn)
    after_rb_revisions = read_schema_revisions_or_exit(conn, "after rollbacks")
    print(f"After rollback object count: {after_rb_count}")
    print(f"After rollback schema revisions: {after_rb_revisions}")

    conn.close()

    print("\n--- Step 6: Verify before == after-rollback counts ---")
    if before_count != after_rb_count:
        print("::error::Object count verification failed! Before count != After-rollback count", file=sys.stderr)
        print(f"::error::Before: {before_count}, After rollback: {after_rb_count}", file=sys.stderr)
        print("\nObject Deltas:", file=sys.stderr)
        print(format_object_deltas(before_map, after_rb_map), file=sys.stderr)
        sys.exit(1)

    print("\n==========================================================================")
    print("✓ SUCCESS: Rollback & object-count verification passed cleanly!")
    print(f"  Objects Before:         {before_count}")
    print(f"  Objects After PR:       {after_mig_count}")
    print(f"  Objects After Rollback: {after_rb_count}")
    print("==========================================================================")


if __name__ == "__main__":
    main()
