#!/bin/bash
# Prints a JSON matrix of the images whose build context changed since <base>.
# An image is a <package>/<major_tag>/ directory holding a Dockerfile. Any changed
# file under it, other than Markdown, counts: the Dockerfile, a COPY'd script, a
# shim source. Deleted images are skipped.
# Usage: changed-images.sh <base rev>
#   e.g. [{"package": "oracle-free", "major_tag": "23"}]
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "usage: $0 <base rev>" >&2
  exit 1
fi
base=$(git rev-parse --verify --quiet "$1^{commit}") || {
  echo "::error::Base '$1' is not a commit in this checkout" >&2
  exit 1
}

# Nearest directory at or above a path that holds a Dockerfile, or nothing
image_dir() {
  local d
  d=$(dirname "$1")
  while [ "${d}" != "." ]; do
    if [ -f "${d}/Dockerfile" ]; then
      echo "${d}"
      return
    fi
    d=$(dirname "${d}")
  done
}

mapfile -t dirs < <(
  git diff --name-only "${base}" HEAD \
    | { grep -v '\.md$' || true; } \
    | while read -r f; do image_dir "${f}"; done \
    | sort -u
)

items=()
for d in "${dirs[@]}"; do
  # Images live at <package>/<major_tag>; a top-level directory has no package
  case "${d}" in */*) ;; *) continue ;; esac
  items+=("{\"package\": \"${d%/*}\", \"major_tag\": \"${d##*/}\"}")
done
(IFS=,; echo "[${items[*]}]")
