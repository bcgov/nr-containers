FROM nginx:1.29.3-alpine3.22

# Install envsubst for environment variable substitution and curl for healthcheck
RUN apk add --no-cache gettext curl

# Copy config template, reusable snippets, and startup script
COPY nginx.conf.template /etc/nginx/nginx.conf.template
COPY conf.d/*.conf /etc/nginx/conf.d/
COPY --chmod=0755 start-nginx.sh /usr/local/bin/start-nginx.sh

EXPOSE 80

# Health check using the /healthz endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -sf http://localhost:80/healthz || exit 1

# Use the startup script as entrypoint
ENTRYPOINT ["/usr/local/bin/start-nginx.sh"]
