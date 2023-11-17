FROM bitnami/postgresql:15.5.0

# Health check and non-privileged user
HEALTHCHECK CMD [ "pg_isready" ]
USER postgres
