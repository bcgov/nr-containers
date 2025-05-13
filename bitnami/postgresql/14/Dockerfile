FROM bitnami/postgresql:14.17.0@sha256:4a8630f79f8a2a46f63b4cb9aa37da85b58fda3afc020d86155f58a2a808d5cb

# Health check and non-privileged user
HEALTHCHECK --interval=15s --timeout=5s --retries=3 CMD [ "pg_isready" ]
USER postgres
