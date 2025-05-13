FROM bitnami/pgpool:4@sha256:e99453bd8b219d8d15bc4948a738bb9069252860eac1ab25a56e6df5f844601e
HEALTHCHECK --interval=30s --timeout=10s --retries=10 \
  CMD pgpool -n || exit 1

USER 1001
