FROM bitnami/postgresql:13.18.0@sha256:bab13eea39c945f3ed34d3c13167d8ff3b3afadd9d0c40f86aca4f5314a1e1d5

# Health check and non-privileged user
HEALTHCHECK --interval=15s --timeout=5s --retries=3 CMD [ "pg_isready" ]
USER postgres
