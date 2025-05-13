FROM postgis/postgis:14-3.5@sha256:609b3d3370332550c6f812ba5fe281296484537a070060e5c58d6fdac1de57e1

# Health check and non-privileged user
HEALTHCHECK --interval=15s --timeout=5s --retries=3 CMD [ "pg_isready" ]
USER postgres
