#!/bin/bash
# Prints the release tag for an image: the tag on its Dockerfile's final FROM.
# Usage: image-tag.sh <image dir>
#   oracle-free/23 (FROM gvenzl/oracle-free:23.26.3-faststart) -> 23.26.3-faststart
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "usage: $0 <image dir>" >&2
  exit 1
fi
file="$1/Dockerfile"
[ -f "${file}" ] || { echo "::error::No Dockerfile at ${file}" >&2; exit 1; }

# Final stage only; FROM is case-insensitive and may carry flags or "AS name"
ref=$(grep -iE '^[[:space:]]*FROM[[:space:]]' "${file}" | tail -n 1 \
  | awk '{for (i = 2; i <= NF; i++) if ($i !~ /^--/) { print $i; exit }}')
ref=${ref%%@*}
name=${ref##*/}
case "${name}" in
  *:*) tag=${name##*:} ;;
  *) echo "::error::Final FROM in ${file} has no tag: '${ref}'" >&2; exit 1 ;;
esac
echo "${tag}"
