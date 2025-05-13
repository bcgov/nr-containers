FROM bitnami/postgresql:16.6.0@sha256:233f361c5819c180b600d110d7da953bea6f1a00764752643ffb7b78ba85c628

# Health check and non-privileged user
HEALTHCHECK --interval=15s --timeout=5s --retries=3 CMD [ "pg_isready" ]
USER postgres
