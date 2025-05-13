FROM mongo:6@sha256:dc5511199234dacbb52f9a404bb7d098a4a70d9801d00c01f392395e983e58e8

# Health check
HEALTHCHECK --interval=15s --timeout=5s --retries=3 CMD ["mongosh", "--eval", "db.adminCommand('ping')"]

# Non-root user (default)
USER mongodb

# Start with custom config to keep resource usage down
COPY --chown=mongodb:mongodb ../mongod.conf /etc/
CMD ["mongod", "--config", "/etc/mongod.conf"]
