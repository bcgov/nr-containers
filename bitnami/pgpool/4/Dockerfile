FROM bitnami/pgpool:4
HEALTHCHECK --interval=30s --timeout=10s --retries=10 \
  CMD pgpool -n || exit 1

USER 1001
