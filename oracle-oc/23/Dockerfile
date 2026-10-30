FROM ghcr.io/bcgov/nr-containers/oracle-free:23.26.3-faststart

COPY db_init/ /container-entrypoint-initdb.d/
COPY startup/ /container-entrypoint-startdb.d/

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 CMD ["sh", "-c", "${ORACLE_BASE}/healthcheck.sh >/dev/null || exit 1"]

ENTRYPOINT ["/entrypoint-wrapper.sh"]

