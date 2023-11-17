FROM postgres:15.5

# Health check and non-privileged user
HEALTHCHECK CMD [ "pg_isready" ]
USER postgres
