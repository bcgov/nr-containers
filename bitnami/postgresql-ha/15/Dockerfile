FROM bitnami/postgresql-repmgr:15@sha256:0fbe148bb74fba195718ef7544f3b7cb21445b88f12da350cbb5842a3c798885

# Health check and non-privileged user
HEALTHCHECK --interval=15s --timeout=5s --retries=3 CMD [ "pg_isready" ]
USER postgres
