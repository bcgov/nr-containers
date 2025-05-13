FROM bitnami/postgresql:12.20.0@sha256:719409d26acf39523f00f5ff1c42e5bc12fd06d28186b7b14f29c81f47b6aead

# Health check and non-privileged user
HEALTHCHECK --interval=15s --timeout=5s --retries=3 CMD [ "pg_isready" ]
USER postgres
