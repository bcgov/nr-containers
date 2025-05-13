FROM postgres:15.12@sha256:8f6fbd24a12304d2adc332a2162ee9ff9d6044045a0b07f94d6e53e73125e11c

# Health check and non-privileged user
HEALTHCHECK --interval=15s --timeout=5s --retries=3 CMD [ "pg_isready" ]
USER postgres
