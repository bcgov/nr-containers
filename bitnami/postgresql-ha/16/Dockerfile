FROM bitnami/postgresql-repmgr:16@sha256:c50dcc8411a95dcdbfd5597e676a9b650cf2f865e0bfc23ab5703129ec02701f

# Health check and non-privileged user
HEALTHCHECK --interval=15s --timeout=5s --retries=3 CMD [ "pg_isready" ]
USER postgres
