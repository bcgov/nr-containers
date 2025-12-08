FROM nginx:1.29-alpine

# Install envsubst for environment variable substitution
RUN apk add --no-cache gettext

# Copy config template, reusable snippets, and startup script
COPY nginx.conf /etc/nginx/nginx.conf.template
COPY conf.d/*.conf /etc/nginx/conf.d/
COPY --chmod=0755 start-nginx.sh /usr/local/bin/start-nginx.sh

EXPOSE 80

# Health check using the /healthz endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -qO- http://localhost:80/healthz || exit 1

# Use the startup script as entrypoint
ENTRYPOINT ["/usr/local/bin/start-nginx.sh"]
