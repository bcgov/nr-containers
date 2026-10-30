# Alembic Migration Framework

This directory contains the Alembic migration infrastructure for the MOF database,
configured for Oracle database migrations.

The env.py tweaks alembic to work with pure sql files, looking in the directory
scripts/<schema>/<object_type> for sql files it should run.  It should work
exactly the same way that flyways works except it uses two database tables
to cache the versions that have been applied against the database.

ALEMBIC_VERSION_SQL - keep track of the V based migrations that have been applied
ALEMBIC_REPEATABLE_SQL - keeps a record of the checksums for the repeatables, allowing
                         changes to be detected and run.

## Directory Structure

```
alembic/
├── env.py                      # Database connection & migration runner
├── alembic.ini                 # Alembic configuration
└── README.md                   # This file

scripts/
├──<schema>*/
│   ├── callbacks/
│   ├── TABLES/
│   ├── SEQUENCES/
│   ├── INDEXES/
│   ├── CONSTRAINTS/
│   ├── REF_CONSTRAINTS/
│   ├── MATERIALIZED_VIEWS/
│   ├── VIEWS/
│   ├── FUNCTIONS/
│   ├── PROCEDURES/
│   ├── PACKAGES/
│   ├── PACKAGE_BODIES/
│   ├── TYPES/
│   ├── TYPE_BODIES/
│   ├── TRIGGERS/
│   ├── SYNONYMS/
│   ├── GRANTS/
│   ├── _DML/
│   └── _ROLLBACKS/
```

## Setup

### 1. Requirements

* python 3 - Development work used 3.13
* uv       - Used to manage venv / dependencies
* oracle database / schema - somewhere you can run alembic against.

For local dev env you can use the one in the docker compose.

`docker compose up oracle-alembic` - will create an empty oracle database that you
                                  can connect to.

There isn't really any setup as `uv` will detect if an env exists when you attempt
to run any scripts and build it if it doesn't exist automagically.

### 2. Set Environment Variables

Alembic reads Oracle connection parameters from environment variables:

The value below will allow you to connect to the oracle database that the docker
compose provides.

```bash
export ORACLE_USER=THE
export ORACLE_PASSWORD=default
export ORACLE_HOST=localhost
export ORACLE_PORT=1526
export ORACLE_SERVICE=DBDOCK_01
```

Or when using Dorker Compose, these are pre-configured from `docker-compose.yml`.
Integration with the Dorker has not been completed yet.

### 3. Verify Installation

```bash
cd <repository root>
./alembic.sh --schema THE status
```

## Migration Categories

### Versioned Migrations (V files)

**Purpose:** One-time DDL changes that execute exactly once and are immutable.

**Categories:**
- TABLES: `CREATE TABLE` statements
- SEQUENCES: `CREATE SEQUENCE` statements
- INDEXES: `CREATE INDEX` statements
- CONSTRAINTS: `ALTER TABLE ADD CONSTRAINT (PK or UNIQUE)`
- REF_CONSTRAINTS: `ALTER TABLE ADD CONSTRAINT (FOREIGN KEY)`
- MATERIALIZED_VIEWS: `CREATE MATERIALIZED VIEW` statements
- SYNONYMS: `CREATE SYNONYM` statements
- GRANTS: `GRANT/REVOKE` permissions

**Characteristics:**
- In a nutshell functionality and naming uses the flyway standard.
- Named: `V<version>__<description>.sql` (from Flyway) → `<revision>_<slug>.py` (Alembic)
- Immutable once committed to main branch, create a new V file with alters to modify
- Execute in order by revision

### Repeatable Migrations (R files)

**Purpose:** DDL objects that can be safely re-created (functions, views, etc.).

**Categories:**
- VIEWS: `CREATE OR REPLACE VIEW` statements
- FUNCTIONS: `CREATE OR REPLACE FUNCTION` statements
- PROCEDURES: `CREATE OR REPLACE PROCEDURE` statements
- PACKAGES: `CREATE OR REPLACE PACKAGE` statements
- PACKAGE_BODIES: `CREATE OR REPLACE PACKAGE BODY` statements
- TYPES: `CREATE OR REPLACE TYPE` statements
- TYPE_BODIES: `CREATE OR REPLACE TYPE BODY` statements
- TRIGGERS: `CREATE OR REPLACE TRIGGER` statements

**Characteristics:**
- Named: `R__<number>_<description>.sql` (from Flyway)
- Can be modified even after merge (if marked as repeatable in Alembic)
- Use `CREATE OR REPLACE` for idempotency
- Include `depends_on` list pointing to prerequisite versioned migrations
- Use `branch_labels = ("repeatable",)` marker

### Callback Migrations

**Purpose:** Hook deployment-time SQL into Flyway-compatible lifecycle events.

**Location:** `scripts/<schema>/callbacks/`

**Supported callback filenames:**
- `beforeMigrate.sql`
- `afterMigrate.sql`
- `beforeEachMigrate.sql`
- `afterEachMigrate.sql`

**Characteristics:**
- Uses Flyway callback names so the repository structure stays compatible with Flyway docs.
- Executes with the same SQL placeholder substitution and Oracle statement parsing used by normal migrations.
- Runs only during `upgrade` flows.
- `afterMigrate.sql` runs after versioned migrations and repeatables complete, which makes it the right hook for schema recompiles.

**Migration File Template:**

### DBA Migrations

**Purpose:** System-level operations requiring DBA privileges.

**Categories:**
- USERS: Create database users
- ROLES: Create database roles
- PROFILES: Create database profiles
- TABLESPACES: Create tablespaces
- DIRECTORIES: Create directory objects
- GRANTS: Grant system-level privileges

**Same structure as versioned migrations** - these are immutable, one-time operations.

#### Running DBA migrations

* make sure ORACLE_USER is set to `SYS`
* to run them all:

```bash
./alembic.sh --schema DBA upgrade head
```

### Apply Migrations

```bash
alembic.sh --schema <schema> upgrade         # Upgrade to latest
alembic.sh --schema <schema> upgrade-to +1      # Upgrade one step
alembic.sh --schema <schema> upgrade-to <rev>   # Upgrade to specific revision
```

### Preview Migrations (Dry Run)

To preview which files would be executed during an upgrade or downgrade without making any changes to the database:

```bash
./alembic.sh --schema <schema> upgrade --dry-run          # Preview upgrade to head
./alembic.sh --schema <schema> upgrade-to <rev> --dry-run  # Preview upgrade to a specific version
./alembic.sh --schema <schema> downgrade -1 --dry-run      # Preview downgrade one step
```

The `--dry-run` flag prints an untruncated summary of all files that would run (including callbacks, versioned migrations, and changed repeatables) in execution order without modifying database tables or applying changes.

### Baseline Migrations (Pre-Existing Databases)

```bash
alembic.sh --schema <schema> baseline            # Baseline to latest (head) without running scripts
alembic.sh --schema <schema> baseline <rev>      # Baseline to specific version (e.g., 16.00096)
```

### Rollback Migrations

```bash
alembic.sh --schema <schema> downgrade -1          # Downgrade one step
alembic.sh --schema <schema> downgrade -2          # Downgrade two steps
alembic.sh --schema <schema> downgrade V1.00004    # Downgrade to specific version
alembic.sh --schema <schema> downgrade base        # Downgrade all the way
```

**Benefits of Flyway version numbers:**
- Maintains version consistency with existing Flyway migrations
- Makes migration history visible in filenames: `1_1_create_products_table.py`, `1_2_add_user_index.py`
- Easy dependency tracking: `down_revision = "1_1"` shows clearly which migration depends on which
- Familiar numbering scheme for teams migrating from Flyway
- required to provide flyway compatibility

## Best Practices - overall

1. **One logical change per migration**
   - Keep migrations focused and small
   - Easier to understand, test, and rollback

2. **Always include downgrade logic**
   - Critical for rollback capability
   - Test downgrades regularly

3. **Use schema-qualified names**
   ```sql
   -- Good
   CREATE TABLE THE.PRODUCTS (...)

   -- Avoid - assumes current schema
   CREATE TABLE PRODUCTS (...)
   ```

4. **For re-creatable objects (views, packages, procedures, etc.) use CREATE OR REPLACE**
   ```sql
   -- Good - idempotent
   CREATE OR REPLACE FUNCTION THE.GET_TOTAL(...)

   -- Avoid - fails if function exists
   CREATE FUNCTION THE.GET_TOTAL(...)
   ```


5. **Test migrations locally first**


   ```bash
   # Upgrade
   alembic.sh --schema <schema> upgrade

   # Test downgrade
   alembic.sh --schema <schema> downgrade -1

   # Upgrade again to verify idempotency
   alembic.sh --schema <schema> upgrade
   ```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ORACLE_USER` | THE | Database user/schema |
| `ORACLE_PASSWORD` | default | Database password |
| `ORACLE_HOST` | localhost | Database host |
| `ORACLE_PORT` | 1526 | Database port |
| `ORACLE_SERVICE` | DBDOCK_01 | Database service name |
| `DEBUG` | (unset) | Set to `1` to show full Python tracebacks and the failing SQL statement on errors |

## Troubleshooting

### A migration script fails

By default a failing statement reports only the script and the Oracle error, then
exits non-zero:

```
ERROR [alembic.env - 1690] Migration failed: /app/scripts/THE/GRANTS/V202609031200.1__ZZ_TEST_FAIL.sql
  ORA-00942: table or view "THE"."TABLE_THAT_DOES_NOT_EXIST" does not exist
Help: https://docs.oracle.com/error-help/db/ora-00942/
```

Each statement is committed individually, so nothing before the failing statement
is rolled back, and the failing revision is **not** recorded in `ALEMBIC_VERSION_SQL`.
Fix the script and re-run `upgrade`; it resumes at the failed revision.

### Getting the full traceback

Set `DEBUG=1` to get the complete chained exception (oracledb -> SQLAlchemy ->
`MigrationSQLError`) plus a debug log line containing the exact statement that failed:

```bash
# local
DEBUG=1 ./alembic.sh --schema THE upgrade

# docker compose (DEBUG is passed through to the alembic-all container)
DEBUG=1 docker compose up alembic-all
```

Alternatively flip `level = DEBUG` on `[logger_alembic.env]` in `alembic.ini` for
persistent verbose logging.

# Using Alembic on Pre-Existing Databases

When introducing Alembic to an existing database whose schema objects are already present (but the Alembic version tracking table does not exist or is missing prior migration records), you should **baseline** the database instead of executing migrations from scratch.

Baselining marks the database at a specific version without running any of the migration DDL scripts.

## Baselining Commands

```bash
# Baseline a pre-existing schema to the latest version (head)
alembic.sh --schema THE baseline

# Baseline a pre-existing schema to a specific version
alembic.sh --schema THE baseline 16.00096

# Baseline DBA/SYS schema (requires SYS credentials)
ORACLE_USER=SYS ORACLE_PASSWORD=syspassword alembic.sh --schema DBA baseline
```

After baselining:
* Running `alembic.sh --schema THE upgrade` will only execute migrations newer than the baseline version.
* Running `alembic.sh --schema THE status` will reflect the baseline version as the current DB revision.

## Manual Verification & Sanity Testing

The baselining feature was verified through the following manual testing workflow against an active database:

1. **Simulate Unmanaged Pre-Existing DB**: Dropped `THE.ALEMBIC_VERSION_SQL` and `THE.ALEMBIC_REPEATABLE_SQL` tables from the database.
2. **Verify Untracked State**: Ran `./alembic.sh --schema THE status`, confirming `Current DB revision: None` and all local migrations (28,769 total) were listed as pending.
3. **Execute Baseline**: Ran `./alembic.sh --schema THE baseline 16.00096`. Alembic stamped all versioned migrations `<= 16.00096` and current repeatable scripts into the newly created tracking tables without executing any DDL statements.
4. **Verify Baselined State**: Ran `./alembic.sh --schema THE status`, confirming `Current DB revision: 16.00096` and pending migrations dropped from 28,769 down to only those newer than `16.00096` (772 remaining).
5. **Verify Upgrade Continuation**: Ran `./alembic.sh --schema THE upgrade` to ensure subsequent migrations applied smoothly from the baseline point.

---

## Comparison: Flyway `baseline` vs Alembic `baseline`

While both approaches achieve the same functional goal—allowing new migrations to run on an existing database without re-executing older scripts—they handle metadata slightly differently under the hood:

| Feature | Flyway `baseline` | Alembic `baseline` (This Repo) |
| :--- | :--- | :--- |
| **Command** | `flyway baseline -baselineVersion="<v>"` | `alembic.sh --schema <schema> baseline [v]` |
| **Version Table Rows** | Inserts **1 single row** with type `BASELINE` | Populates **each historical version** up to target with disk checksums |
| **Checksums Stored** | `null` | Calculated from local migration files |
| **Integrity Validation** | Skips checksum validation for migrations `<= baseline` | Validates that local migration files match the baseline checksums |
| **Subsequent `upgrade`** | Only executes scripts `> baseline` | Only executes scripts `> baseline` |
| **Rollback / `downgrade`** | Not supported in Flyway Community | Supports step-by-step downgrade past baseline if undo (`U`) scripts exist |
| **Repeatables (`R__`)** | Manually managed | Automatically stamps current repeatable checksums |


## References
Objective of this work is to provide backward compatibility with flyway, The
first link describes how to create flyway compatilble sql database migrations,
the rest of the docs are just background.

- [Flyway Migrations](https://documentation.red-gate.com/fd/getting-started-with-flyway-184127223.html)
- [Alembic Documentation](https://alembic.sqlalchemy.org/)
- [SQLAlchemy Oracle Dialect](https://docs.sqlalchemy.org/en/20/dialects/oracle.html)
- [Oracle SQL Reference](https://docs.oracle.com/en/database/oracle/oracle-database/)
