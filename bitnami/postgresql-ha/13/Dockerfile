FROM bitnami/postgresql-repmgr:13@sha256:702ad1d2dc9db709bfe38e72f1f0f160f7e1be30ea7215b9c817c7d3e7dc2e67

# Health check and non-privileged user
HEALTHCHECK --interval=15s --timeout=5s --retries=3 CMD [ "pg_isready" ]
USER postgres
