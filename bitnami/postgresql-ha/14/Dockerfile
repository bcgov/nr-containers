FROM bitnami/postgresql-repmgr:14@sha256:23cda85f091d69c379d5c2ce2e2477609525d7853818f2dd6c6b1a474142c1be

# Health check and non-privileged user
HEALTHCHECK --interval=15s --timeout=5s --retries=3 CMD [ "pg_isready" ]
USER postgres
