# alembic

Migration runner image for [bcgov-c/nr-mof-db](https://github.com/bcgov-c/nr-mof-db): Python, Alembic, oracledb and the nr-mof-db runner helpers (`alembic/`, `alembic.sh`, `migration_driver.sh`, `run_*_migrations.sh`).

No SQL is included. Migration scripts stay in nr-mof-db and are mounted into `/app/scripts` from a PVC at runtime.

Image: `ghcr.io/bcgov/nr-containers/alembic:3.14-slim`

Runner files are vendored from nr-mof-db; when they change there, copy them here and open a PR.
