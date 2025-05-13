FROM mongo:7.0.20@sha256:01a0a34dcf977a82ebb275e3f1668fc4428e6fd961e8d1d25424902bb8152933

# Health check
HEALTHCHECK --interval=15s --timeout=5s --retries=3 CMD ["mongosh", "--eval", "db.adminCommand('ping')"]

# Non-root user (default)
USER mongodb

# Start with custom config to keep resource usage down
COPY --chown=mongodb:mongodb ../mongod.conf /etc/
CMD ["mongod", "--config", "/etc/mongod.conf"]
