FROM bitnami/postgresql:15.10.0@sha256:e989bcc1772cd82ef46bd03d3e6bf7ea35011b39a7826d828886cb9c45aec819

# Health check and non-privileged user
HEALTHCHECK --interval=15s --timeout=5s --retries=3 CMD [ "pg_isready" ]
USER postgres
