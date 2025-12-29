#!/usr/bin/env sh
# Startup script for nginx with environment variable substitution and retry logic
# Alpine-compatible, POSIX sh

set -eu
set -o pipefail 2>/dev/null || true  # pipefail not available in all POSIX shells

# Env vars you can override at runtime:
#   MAX_RETRIES      - total restart attempts (default: 30)
#   DELAY_SECONDS    - delay between attempts in seconds (default: 5)

MAX_RETRIES="${MAX_RETRIES:-30}"
DELAY_SECONDS="${DELAY_SECONDS:-5}"

ts() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }

# Required environment variables
REQUIRED_VARS="AZURE_OPENAI_HOST AZURE_DOCUMENT_INTELLIGENCE_HOST AZURE_SEARCH_HOST AZURE_COSMOS_HOST"

# Check required environment variables
for var in $REQUIRED_VARS; do
    eval "val=\${$var:-}"
    if [ -z "$val" ]; then
        echo "$(ts) - ERROR: Required environment variable $var is not set"
        exit 1
    fi
done

echo "$(ts) - Substituting environment variables in nginx config..."

# Substitute environment variables in the nginx config template
# Using envsubst to replace ${VAR} placeholders with actual values
envsubst '${AZURE_OPENAI_HOST} ${AZURE_DOCUMENT_INTELLIGENCE_HOST} ${AZURE_SEARCH_HOST} ${AZURE_COSMOS_HOST}' \
    < /etc/nginx/nginx.conf.template \
    > /etc/nginx/nginx.conf

echo "$(ts) - Configuration generated successfully"

# Test nginx configuration
if ! nginx -t 2>&1; then
    echo "$(ts) - ERROR: nginx configuration test failed"
    exit 1
fi

echo "$(ts) - Configuration test passed"

# Signal handling
stop=0

on_term() {
    stop=1
    echo "$(ts) - Received termination signal; gracefully stopping nginx..."
    nginx -s quit 2>/dev/null || true
}
trap on_term INT TERM

# Retry loop
attempt=1
while [ "$attempt" -le "$MAX_RETRIES" ] && [ "$stop" -eq 0 ]; do
    echo "$(ts) - Starting nginx (attempt $attempt/$MAX_RETRIES)"
    
    # Run nginx in foreground
    if nginx -g 'daemon off;'; then
        echo "$(ts) - nginx exited cleanly (code 0). Not retrying."
        exit 0
    fi

    if [ "$stop" -eq 1 ]; then
        echo "$(ts) - Shutdown requested. Exiting."
        exit 0
    fi

    echo "$(ts) - nginx exited with non-zero code"
    attempt=$((attempt + 1))

    if [ "$attempt" -le "$MAX_RETRIES" ]; then
        echo "$(ts) - Waiting $DELAY_SECONDS seconds before retry..."
        sleep "$DELAY_SECONDS"
    fi
done

if [ "$stop" -eq 0 ]; then
    echo "$(ts) - ERROR: Exhausted $MAX_RETRIES retries. Giving up."
    exit 1
fi

exit 0
