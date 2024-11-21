FROM bitnami/postgresql:14.14.0

# Health check and non-privileged user
HEALTHCHECK --interval=15s --timeout=5s --retries=3 CMD [ "pg_isready" ]
USER postgres
