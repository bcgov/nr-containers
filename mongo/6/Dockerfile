FROM mongo:6@sha256:89def6a7f74a8565484db4a53ffc3d3276376beadd66ff6b78e55a9ee8fc390f

# Health check
HEALTHCHECK --interval=15s --timeout=5s --retries=3 CMD ["mongosh", "--eval", "db.adminCommand('ping')"]

# Non-root user (default)
USER mongodb

# Start with custom config to keep resource usage down
COPY --chown=mongodb:mongodb ../mongod.conf /etc/
CMD ["mongod", "--config", "/etc/mongod.conf"]
