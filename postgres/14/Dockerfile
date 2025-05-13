FROM postgres:14.17@sha256:4836bc848e0d55e582f56d03f0ea89ee03fc33585cf46484f16233151613fd47

# Health check and non-privileged user
HEALTHCHECK --interval=15s --timeout=5s --retries=3 CMD [ "pg_isready" ]
USER postgres
