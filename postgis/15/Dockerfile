FROM postgis/postgis:15-3.5@sha256:61e10dc8602075b79e5d072ac4b74cf607ade3820627d19c8ea9757431da77dd

# Health check and non-privileged user
HEALTHCHECK --interval=15s --timeout=5s --retries=3 CMD [ "pg_isready" ]
USER postgres
