FROM postgres:16.8@sha256:301bcb60b8a3ee4ab7e147932723e3abd1cef53516ce5210b39fd9fe5e3602ae

# Health check and non-privileged user
HEALTHCHECK --interval=15s --timeout=5s --retries=3 CMD [ "pg_isready" ]
USER postgres
