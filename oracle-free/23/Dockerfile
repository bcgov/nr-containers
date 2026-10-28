FROM gvenzl/oracle-free:23.26.3-slim-faststart

USER root

# Enable arbitrary OpenShift UIDs (Red Hat standard: root group ownership and group-writable)
RUN chgrp -R 0 ${ORACLE_BASE} && \
    chmod -R g=u ${ORACLE_BASE} && \
    chmod g=u /etc/passwd

# Dynamic user entrypoint wrapper for OpenShift arbitrary UIDs
COPY --chmod=755 entrypoint-wrapper.sh /usr/local/bin/entrypoint-wrapper.sh

USER oracle

HEALTHCHECK --interval=20s --timeout=5s --start-period=10s --retries=3 CMD ["sh", "-c", "${ORACLE_BASE}/healthcheck.sh >/dev/null || exit 1"]

ENTRYPOINT ["/usr/local/bin/entrypoint-wrapper.sh"]
