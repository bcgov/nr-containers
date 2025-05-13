FROM postgres:13.20@sha256:7dad293647281f6a0f0b7b9b7adc3c27775d2adc821d8ccd9d2ff72ef503a1c8

# Health check and non-privileged user
HEALTHCHECK --interval=15s --timeout=5s --retries=3 CMD [ "pg_isready" ]
USER postgres
