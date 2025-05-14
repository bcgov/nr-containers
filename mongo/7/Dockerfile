FROM mongo:7.0.20@sha256:30e5dc22a38342e3dc84e51acb8e4059f87bf6ba9d9f4d04d4250fad89514945

# Health check
HEALTHCHECK --interval=15s --timeout=5s --retries=3 CMD ["mongosh", "--eval", "db.adminCommand('ping')"]

# Non-root user (default)
USER mongodb

# Start with custom config to keep resource usage down
COPY --chown=mongodb:mongodb ../mongod.conf /etc/
CMD ["mongod", "--config", "/etc/mongod.conf"]
