# alembic

Thin, reusable base for Alembic/Flyway-style migration runners against Oracle (incl. monolithic, multi-schema databases).

Image: `ghcr.io/bcgov/nr-containers/alembic:3.14-slim`

Contains only `python:3.14-slim` and a virtualenv at `/opt/venv` (on `PATH`, `VIRTUAL_ENV` set) with the shared deps in [`3.14/runner/pyproject.toml`](3.14/runner/pyproject.toml): alembic, sqlalchemy, oracledb (thin mode), jproperties, xxhash. `/app` is an empty, world-writable workdir.

It contains **no** app runner, `env.py`, schema configs, shell drivers or SQL. Those stay in your team's repo.

## Using it

Pull the public base, then add your team's content after pull:

- **CI / OpenShift (recommended):** check out your repo on the runner (`GITHUB_TOKEN`, no PAT), stream your runner (`alembic/`, drivers) and SQL into a PVC, mount it in the migration Job and copy it into `/app` before running. No second image to publish, no pull secret.
- **Local/dev (optional):** a thin layer in your repo:

  ```dockerfile
  FROM ghcr.io/bcgov/nr-containers/alembic:3.14-slim
  COPY alembic/ /app/alembic/
  COPY *.sh /app/
  ```

Need another dependency? If it's broadly useful for Oracle migrations, open a PR here; otherwise `pip install` it in your own layer. Reference consumer: [bcgov-c/nr-mof-db](https://github.com/bcgov-c/nr-mof-db) (`.github/actions/populate-scripts-pvc`, `.github/actions/run-migrations`).
