"""Convert Flyway SQL migrations to Alembic Python migrations.

This utility helps migrate existing Flyway SQL migrations to Alembic format.

Usage:
    python alembic/migrate_flyway.py scripts/THE alembic/THE
    python alembic/migrate_flyway.py scripts/DBA alembic/DBA

"""

import argparse
import re
from pathlib import Path
from typing import Optional


try:
    import flyway_migration_name_validator as flyway_validator
except ImportError:
    from . import flyway_migration_name_validator as flyway_validator


def parse_flyway_filename(filename: str) -> dict:

    """Parse Flyway migration filename.

    Flyway patterns:
    - V1.1__description.sql (versioned)
    - R__description.sql (repeatable)
    - U1.1__undo_description.sql (undo)

    Returns dict with parsed components or empty if not a migration.
    """
    info = flyway_validator.parse_migration_filename(filename)
    if not info:
        return {}

    if info.migration_type == "versioned":
        return {
            "type": "versioned",
            "version": info.version,
            "name": info.description,
            "filename": filename,
        }
    elif info.migration_type == "repeatable":
        # Handle optional leading number in repeatable description (e.g. 1_name)
        desc = info.description
        parts = desc.split("_", 1)
        number = parts[0] if len(parts) > 1 and parts[0].isdigit() else "1"
        name = parts[1] if len(parts) > 1 and parts[0].isdigit() else desc
        return {
            "type": "repeatable",
            "number": number,
            "name": name,
            "filename": filename,
        }
    elif info.migration_type == "undo":
        return {"type": "undo", "filename": filename}

    return {}



def detect_object_type(sql_content: str) -> str:
    """Detect type of DDL object from SQL content."""
    upper = sql_content.upper()

    if "CREATE TABLE" in upper or "ALTER TABLE" in upper:
        if "ADD CONSTRAINT" in upper:
            if "FOREIGN KEY" in upper:
                return "ref_constraint"
            return "constraint"
        return "table"
    elif "CREATE SEQUENCE" in upper:
        return "sequence"
    elif "CREATE INDEX" in upper or "CREATE UNIQUE INDEX" in upper:
        return "index"
    elif "CREATE MATERIALIZED VIEW" in upper:
        return "materialized_view"
    elif "CREATE VIEW" in upper or "CREATE OR REPLACE VIEW" in upper:
        return "view"
    elif "CREATE FUNCTION" in upper or "CREATE OR REPLACE FUNCTION" in upper:
        return "function"
    elif "CREATE PROCEDURE" in upper or "CREATE OR REPLACE PROCEDURE" in upper:
        return "procedure"
    elif "CREATE PACKAGE" in upper or "CREATE OR REPLACE PACKAGE" in upper:
        if "BODY" in upper:
            return "package_body"
        return "package"
    elif "CREATE TYPE" in upper or "CREATE OR REPLACE TYPE" in upper:
        if "BODY" in upper:
            return "type_body"
        return "type"
    elif "CREATE TRIGGER" in upper or "CREATE OR REPLACE TRIGGER" in upper:
        return "trigger"
    elif "CREATE SYNONYM" in upper:
        return "synonym"
    elif "GRANT" in upper or "REVOKE" in upper:
        return "grant"

    return "unknown"


def get_category_dir(obj_type: str) -> str:
    """Get the Alembic category directory for an object type."""
    mapping = {
        "table": "TABLES",
        "sequence": "SEQUENCES",
        "index": "INDEXES",
        "constraint": "CONSTRAINTS",
        "ref_constraint": "REF_CONSTRAINTS",
        "materialized_view": "MATERIALIZED_VIEWS",
        "view": "VIEWS",
        "function": "FUNCTIONS",
        "procedure": "PROCEDURES",
        "package": "PACKAGES",
        "package_body": "PACKAGE_BODIES",
        "type": "TYPES",
        "type_body": "TYPE_BODIES",
        "trigger": "TRIGGERS",
        "synonym": "SYNONYMS",
        "grant": "GRANTS",
    }
    return mapping.get(obj_type, "UNKNOWN")


def is_repeatable(obj_type: str) -> bool:
    """Check if object type should be repeatable (R file)."""
    repeatable_types = {
        "view",
        "function",
        "procedure",
        "package",
        "package_body",
        "type",
        "type_body",
        "trigger",
    }
    return obj_type in repeatable_types


def generate_migration(
    metadata: dict,
    sql_content: str,
    obj_type: str,
    schema: str = "THE",
) -> str:
    """Generate Alembic Python migration from Flyway SQL.

    Args:
        metadata: Parsed Flyway filename metadata
        sql_content: SQL file content
        obj_type: Type of database object
        schema: Database schema name

    Returns:
        Python migration file content
    """

    if metadata["type"] == "versioned":
        version = metadata["version"].replace(".", "_")
        name = metadata["name"]
        revision_id = f"{version}_{name}"
    else:  # repeatable
        revision_id = metadata["name"]

    # Determine revision structure
    if metadata["type"] == "repeatable":
        down_rev = "None"
        branch_labels = '("repeatable",)'
        depends_on = "None"
    else:
        down_rev = "None"
        branch_labels = "None"
        depends_on = "None"

    # Escape SQL for Python string
    sql_escaped = sql_content.replace('"""', r'\"\"\"')

    # Try to extract object name for downgrade
    downgrade_sql = f"-- Downgrade for {obj_type}"
    if "function" in obj_type.lower():
        match = re.search(
            r"(?:CREATE\s+OR\s+REPLACE\s+)?FUNCTION\s+(?:(?:"
            + schema
            + r"|\"" + schema + r"\")\.)?\s*(\w+)",
            sql_content.upper(),
        )
        if match:
            obj_name = match.group(1)
            downgrade_sql = f"DROP FUNCTION {schema}.{obj_name}"
    elif "procedure" in obj_type.lower():
        match = re.search(
            r"(?:CREATE\s+OR\s+REPLACE\s+)?PROCEDURE\s+(?:(?:"
            + schema
            + r"|\"" + schema + r"\")\.)?\s*(\w+)",
            sql_content.upper(),
        )
        if match:
            obj_name = match.group(1)
            downgrade_sql = f"DROP PROCEDURE {schema}.{obj_name}"
    elif "view" in obj_type.lower():
        match = re.search(
            r"(?:CREATE\s+OR\s+REPLACE\s+)?(?:FORCE\s+)?VIEW\s+(?:(?:"
            + schema
            + r"|\"" + schema + r"\")\.)?\s*(\w+)",
            sql_content.upper(),
        )
        if match:
            obj_name = match.group(1)
            downgrade_sql = f"DROP VIEW {schema}.{obj_name}"
    elif "table" in obj_type.lower() and "constraint" not in obj_type.lower():
        match = re.search(
            r"CREATE\s+(?:GLOBAL\s+TEMPORARY\s+)?TABLE\s+(?:(?:"
            + schema
            + r"|\"" + schema + r"\")\.)?\s*(\w+)",
            sql_content.upper(),
        )
        if match:
            obj_name = match.group(1)
            downgrade_sql = f"DROP TABLE {schema}.{obj_name}"

    template = f'''"""Converted from Flyway: {metadata.get("filename", "unknown")}

Revision ID: {revision_id}
Revises: {'None' if metadata["type"] == 'versioned' else 'None'}
Create Date: 2026-03-03

Object type: {obj_type}
Flyway type: {metadata["type"]}

Generated by migrate_flyway.py utility.
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "{revision_id}"
down_revision = {down_rev}
branch_labels = {branch_labels}
depends_on = {depends_on}


def upgrade() -> None:
    """Apply migration."""
    op.execute("""
{sql_escaped}
    """)


def downgrade() -> None:
    """Rollback migration."""
    # TODO: Verify and customize downgrade
    op.execute("{downgrade_sql}")
'''

    return template


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Convert Flyway migrations to Alembic Python migrations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python alembic/migrate_flyway.py scripts/THE alembic/THE
  python alembic/migrate_flyway.py scripts/DBA alembic/DBA --dry-run
        """,
    )
    parser.add_argument(
        "source",
        type=Path,
        help="Source directory with Flyway migrations (e.g., scripts/THE)",
    )
    parser.add_argument(
        "target",
        type=Path,
        help="Target Alembic directory (e.g., alembic/THE)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    parser.add_argument(
        "--schema",
        default="THE",
        help="Database schema name (default: THE)",
    )

    args = parser.parse_args()

    source_dir = args.source
    target_dir = args.target
    schema = args.schema

    if not source_dir.is_dir():
        print(f"Error: Source directory not found: {source_dir}")
        return 1

    # Collect migrations by category
    migrations_by_category: dict[str, list] = {}

    for sql_file in sorted(source_dir.rglob("*.sql")):
        metadata = parse_flyway_filename(sql_file.name)
        if not metadata:
            continue

        if metadata["type"] == "undo":
            continue  # Skip undo files

        sql_content = sql_file.read_text()
        obj_type = detect_object_type(sql_content)
        category = get_category_dir(obj_type)

        if category not in migrations_by_category:
            migrations_by_category[category] = []

        migrations_by_category[category].append(
            {
                "file": sql_file,
                "metadata": metadata,
                "sql": sql_content,
                "obj_type": obj_type,
            }
        )

    total = sum(len(v) for v in migrations_by_category.values())
    print(f"Found {total} migrations\n")

    # Generate Alembic migrations
    for category in sorted(migrations_by_category.keys()):
        migrations = migrations_by_category[category]
        category_target = target_dir / category

        print(f"\n{category}:")

        for migration in migrations:
            metadata = migration["metadata"]
            obj_type = migration["obj_type"]

            py_content = generate_migration(
                metadata,
                migration["sql"],
                obj_type,
                schema,
            )

            # Generate filename
            if metadata["type"] == "versioned":
                version = metadata["version"].replace(".", "_")
                name = metadata["name"]
                filename = f"{version}_{name}.py"
            else:
                number = metadata["number"]
                name = metadata["name"]
                filename = f"{number}_{name}.py"

            target_file = category_target / filename

            if args.dry_run:
                print(f"  → {target_file.relative_to(target_dir.parent)}")
            else:
                category_target.mkdir(parents=True, exist_ok=True)
                target_file.write_text(py_content)
                print(f"  ✓ {target_file.relative_to(target_dir.parent)}")

    if args.dry_run:
        print("\n(Use without --dry-run to actually create files)")
    else:
        print(f"\n✓ Conversion complete: {total} migrations created")

    return 0


if __name__ == "__main__":
    exit(main())
