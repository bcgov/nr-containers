FROM bitnami/pgpool:4@sha256:a3b48a0f643c053de95a00524dafdce3487207dcd54dc6c93cc1c1349c4084e6
HEALTHCHECK --interval=30s --timeout=10s --retries=10 \
  CMD pgpool -n || exit 1

USER 1001
