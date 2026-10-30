#!/usr/bin/env python
"""Link SQL files to Alembic while preserving schema/object_type structure.

Usage:
    python alembic/link_sql_migrations.py              # Link TABLES only (default)
    python alembic/link_sql_migrations.py TABLES       # Link TABLES
    python alembic/link_sql_migrations.py VIEWS        # Link VIEWS
    python alembic/link_sql_migrations.py all          # Link all types

This scans scripts/ and copies files to alembic/versions/<schema>/<object_type>/
preserving your organized directory structure.
"""

import re
import sys
from pathlib import Path

try:
    import flyway_migration_name_validator as flyway_validator
except ImportError:
    from . import flyway_migration_name_validator as flyway_validator


def parse_flyway_version(filename: str) -> str | None:
    """Extract version from Flyway filename.

    V1.1__description.sql -> 1_1_description
    V7.02675__CONSTRAINT.sql -> 7_02675_CONSTRAINT
    """
    info = flyway_validator.parse_migration_filename(filename)
    if not info or info.migration_type != "versioned" or not info.version:
        return None

    version = info.version.replace(".", "_")
    desc = info.description
    return f"{version}_{desc}"



def get_schema_and_type(sql_file: Path) -> tuple[str | None, str | None]:
    """Extract schema and object type from file path.

    scripts/THE/TABLES/V1.1__name.sql -> ("THE", "TABLES")
    """
    parts = sql_file.parts
    # Find index of 'scripts'
    if 'scripts' not in parts:
        return None, None

    idx = parts.index('scripts')
    if len(parts) < idx + 3:
        return None, None

    schema = parts[idx + 1]
    obj_type = parts[idx + 2]
    return schema, obj_type


def link_sql_file(sql_file: Path, alembic_dir: Path) -> bool:
    """Create Python wrapper in same nested directory as SQL file.

    Both SQL and Python files organized in: alembic/versions/<schema>/<object_type>/

    Returns True if created, False if already exists or skipped.
    """
    filename = sql_file.name
    slug = parse_flyway_version(filename)

    if not slug:
        return False

    schema, obj_type = get_schema_and_type(sql_file)
    if not schema or not obj_type:
        return False

    # Store both SQL and Python wrapper in organized nested directory
    target_dir = alembic_dir / "versions" / schema / obj_type
    target_dir.mkdir(parents=True, exist_ok=True)

    # Create __init__.py files for Python package structure
    for parent in target_dir.parents:
        if parent >= alembic_dir / "versions":
            init_file = parent / "__init__.py"
            if not init_file.exists():
                init_file.write_text('"""Alembic migrations package."""\n')

    init_file = target_dir / "__init__.py"
    if not init_file.exists():
        init_file.write_text('"""Alembic migrations package."""\n')

    sql_file_target = target_dir / filename
    py_filename = filename.replace('.sql', '').replace('.', '_') + '.py'
    py_file = target_dir / py_filename

    # Check if Python wrapper already exists
    if py_file.exists():
        return False

    # Read the SQL content
    sql_content = sql_file.read_text()

    # Create SQL file (copy)
    if not sql_file_target.exists():
        sql_file_target.write_text(sql_content)

    # Create Python wrapper in same directory
    python_wrapper = f'''"""Alembic migration wrapper for SQL: {filename}

Revision ID: {slug}
Revises: None
Create Date: 2026-03-03
"""
from pathlib import Path
from alembic import op

# Get the SQL file path (same directory)
_sql_file = Path(__file__).parent / "{filename}"

# revision identifiers, used by Alembic.
revision = "{slug}"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Execute SQL migration."""
    with open(_sql_file) as f:
        sql = f.read()
    op.execute(sql)


def downgrade() -> None:
    """Downgrade is not supported for SQL migrations."""
    pass
'''

    py_file.write_text(python_wrapper)
    return True


def main():
    """Link SQL files from scripts/ to alembic/ by schema and object type."""
    # Parse command line args
    object_type_filter = "TABLES"  # Default to TABLES only
    if len(sys.argv) > 1:
        obj_type = sys.argv[1].upper()
        if obj_type != "ALL":
            object_type_filter = obj_type
        else:
            object_type_filter = None  # None means include all

    scripts_dir = Path("scripts")
    alembic_dir = Path("alembic")

    print(f"Linking SQL files to Alembic...\n")
    if object_type_filter:
        print(f"Object type filter: {object_type_filter} only\n")
    else:
        print(f"Object type filter: ALL\n")

    created = 0
    skipped = 0

    # Find all .sql files recursively
    for sql_file in sorted(scripts_dir.rglob("*.sql")):
        # Skip non-Flyway versioned files
        if not sql_file.name.startswith("V"):
            continue

        # Check if file matches object type filter
        _, obj_type = get_schema_and_type(sql_file)
        if object_type_filter and obj_type != object_type_filter:
            continue

        if link_sql_file(sql_file, alembic_dir):
            created += 1
        else:
            skipped += 1

    print(f"\n✓ Complete: {created} linked, {skipped} skipped (or already existed)")

    if object_type_filter:
        print(f"\nSQL {object_type_filter} migrations ready:")
        print(f"  - SQL files: alembic/versions/<schema>/{object_type_filter}/*.sql")
        print(f"  - Python wrappers: alembic/versions/<schema>/{object_type_filter}/*.py")
    else:
        print(f"\nSQL migrations ready:")
        print(f"  - SQL files: alembic/versions/<schema>/<object_type>/*.sql")
        print(f"  - Python wrappers: alembic/versions/<schema>/<object_type>/*.py")

if __name__ == "__main__":
    main()

