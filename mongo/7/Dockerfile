FROM mongo:7.0.26

# Health check
HEALTHCHECK --interval=15s --timeout=5s --retries=3 CMD ["mongosh", "--eval", "db.adminCommand('ping')"]

# Non-root user (default)
USER mongodb

# Start with custom config to keep resource usage down
COPY --chown=mongodb:mongodb ../mongod.conf /etc/
CMD ["mongod", "--config", "/etc/mongod.conf"]
