#!/bin/bash
set -e

# If running with an arbitrary UID not present in /etc/passwd (standard in OpenShift),
# add a mapping for the user so Oracle tools (getpwuid) can resolve the username.
if ! whoami &> /dev/null; then
  if [ -w /etc/passwd ]; then
    echo "oracle:x:$(id -u):0:oracle user:${ORACLE_BASE:-/opt/oracle}:/bin/bash" >> /etc/passwd
  fi
fi

exec container-entrypoint.sh "$@"
