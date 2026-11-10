#!/bin/bash
set -e

# If running with an arbitrary UID not present in /etc/passwd (standard in OpenShift),
# ensure the current UID is mapped to the oracle user and primary GID 0 in /etc/passwd
# so getpwuid, getpwnam, and whoami resolve cleanly without duplicate entries.
if [ -w /etc/passwd ]; then
  CURR_UID=$(id -u)
  if [ "${CURR_UID}" != "$(id -u oracle 2>/dev/null)" ]; then
    grep -v -E "^(oracle|${CURR_UID}):" /etc/passwd > /tmp/passwd.tmp || true
    echo "oracle:x:${CURR_UID}:0:oracle user:${ORACLE_BASE:-/opt/oracle}:/bin/bash" >> /tmp/passwd.tmp
    cat /tmp/passwd.tmp > /etc/passwd
    rm -f /tmp/passwd.tmp
  fi
fi

exec container-entrypoint.sh "$@"
