# Overview

When migrations are run against a database using alembic, we want to be able to
run a recompile of the schema after each set of migrations is run.  Currently we
have a Repeatable migrations that does a recompile after the first set of
migrations is run against a schema, however this only gets run once, and is only
re-run if the repeatable file is modified.

Further to this topic whatever we implement we want it to comply with flyway
convensions allowing for backward compatibility.

Research suggests the flyway callbacks are the solution to this problem.

# Callbacks With Flyway - hypothetical

While we are not using flyway we still want to try to capture how this would work
if we were.  In a nutshell we are going to create a `callbacks` folder in each
schema.  If we were to run migrations using flyway we would add the following
configuration:

```bash
export FLYWAY_LOCATIONS=filesystem:scripts/THE
export FLYWAY_CALLBACKS=filesystem:scripts/THE/callbacks
flyway migrate
```

# Callbacks with Alembic - implemented

Alembic now looks for Flyway-style callback scripts in `scripts/<SCHEMA>/callbacks`.
If a callback file exists, it is executed as raw SQL using the same connection,
placeholder substitution, and statement-splitting rules as normal migrations.

Supported callback names:

- `beforeMigrate.sql` - runs once before the versioned upgrade sequence
- `afterMigrate.sql` - runs once after versioned upgrades and repeatables finish
- `beforeEachMigrate.sql` - runs before each versioned migration file
- `afterEachMigrate.sql` - runs after each versioned migration file

Notes:

- Callbacks currently run for Alembic `upgrade` operations only.
- Repeatable migrations continue to run after versioned upgrades and before `afterMigrate.sql`.
- If a callback file is not present, it is silently skipped.

Example:

```text
scripts/
└── THE/
	├── callbacks/
	│   └── afterMigrate.sql
	├── TABLES/
	└── VIEWS/
```

This is the right place for tasks like recompiling invalid objects after a deployment,
which is exactly the sort of operational glue Flyway callbacks were made for.

