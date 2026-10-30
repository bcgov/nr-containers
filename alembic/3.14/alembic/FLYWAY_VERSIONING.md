# Flyway Version Number Support in Alembic

This document explains how to use Flyway-compatible version numbering in this
repository, which will use alembic to apply the migrations to a database.

## Overview

Customizations in this reposoitories Alembic implementation, enable this repository
to use flyway based version numbers, and plain sql files to define migrations.

## Version Number Format

**Flyway format:** `V<major>.<minor>__<description>.sql`

Examples:
- `V100.1__create_users_table.sql` → `1_1_create_users_table.py` (revision: `V100.1_create_users_table`)
- `V100.2__add_user_index.sql` → `1_2_add_user_index.py` (revision: `V100.2_add_user_index`)


## Creating Migrations with Flyway Versions

## Version Number Semantics

The version number follows semantic versioning principles:

- **Major version** (first number): Schema-level changes or significant features
- **Minor version** (second number): Incremental changes within a feature

Examples:
- `V100.0` → Initial schema
- `V100.1` → Add first table
- `V100.2` → Add second table
- `V100.3` → Add index to first table

## Dependencies and Ordering

### Versioned Migrations

Versioned migrations execute in strict order by revision ID:

example V100.1 -> V100.2 -> V100.3 etc...
and vise versa for downgrades.


## Workflow Example

### Step 1: Create migrations in plain sql and name the file with same version numbers

Example:
* V100.1__some_table.sql
* V100.2__some_index.sql
* V100.3__constraints.sql
* V100.4__fk_constraints.sql

Then also define the rollbacks:
* U100.1__some_table.sql
* U100.2__some_index.sql
* U100.3__constraints.sql
* U100.4__fk_constraints.sql

### Step 2: Execute migrations

```bash
# List what would be applied
./alembic.sh --schema <schema> status

# Baseline a pre-existing schema (mark version without executing scripts)
./alembic.sh --schema <schema> baseline V100.2

# Apply all pending migrations
./alembic.sh --schema <schema> upgrade

# OR upgrade to a specific version
./alembic.sh --schema <schema> upgrade-to V100.2

# Verify
./alembic.sh --schema <schema> status
```


