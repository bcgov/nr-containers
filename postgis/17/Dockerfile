FROM postgis/postgis:17-3.5@sha256:e8355a3817bfc6241d6b3ff28ce99449ec0d73032263d5a5762f08168a5d376f

# Health check and non-privileged user
HEALTHCHECK --interval=15s --timeout=5s --retries=3 CMD [ "pg_isready" ]
USER postgres
