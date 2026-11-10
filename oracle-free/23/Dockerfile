from ghcr.io/oracle/oraclelinux:8-slim as builder

run microdnf install -y gcc glibc-devel && \
    microdnf clean all

copy fakeuid.c build-fakeuid.sh /tmp/
run /tmp/build-fakeuid.sh /usr/local/lib/libfakeuid.so

FROM gvenzl/oracle-free:23.26.3-faststart

USER root

# Preload the UID shim for all binaries to satisfy Oracle's ORA-12753 UID validation under OpenShift
COPY --from=builder /usr/local/lib/libfakeuid.so /usr/local/lib/libfakeuid.so
RUN echo '/usr/local/lib/libfakeuid.so' > /etc/ld.so.preload && \
    chmod 644 /etc/ld.so.preload && \
    chmod 755 /usr/local/lib/libfakeuid.so

# Enable arbitrary OpenShift UIDs (Red Hat standard: root group ownership and group-writable)
# Map Oracle OSDBA/OSOPER/OINSTALL to GID 0 (root group) for OpenShift arbitrary UID compatibility
RUN sed -i -E 's/^(dba|oinstall|oper):x:[0-9]+:/\1:x:0:/' /etc/group && \
    chmod g=u /etc/group && \
    chgrp -R 0 ${ORACLE_BASE} && \
    chmod -R g=u ${ORACLE_BASE} && \
    chmod g=u /etc/passwd

# Dynamic user entrypoint wrapper for OpenShift arbitrary UIDs
COPY --chmod=755 entrypoint-wrapper.sh /usr/local/bin/entrypoint-wrapper.sh

USER oracle

HEALTHCHECK --interval=20s --timeout=5s --start-period=10s --retries=3 CMD ["sh", "-c", "${ORACLE_BASE}/healthcheck.sh >/dev/null || exit 1"]

ENTRYPOINT ["/usr/local/bin/entrypoint-wrapper.sh"]
