FROM bitnami/postgresql-repmgr:12@sha256:6d5d23c1ec4916f18633d5c353b50aa768269d0ec0a16d5972b49f47782cfb56

# Health check and non-privileged user
HEALTHCHECK --interval=15s --timeout=5s --retries=3 CMD [ "pg_isready" ]
USER postgres
