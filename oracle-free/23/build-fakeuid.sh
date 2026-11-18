#!/bin/sh
# Builds the libfakeuid.so UID shim from fakeuid.c.
# Single build definition: the Dockerfile builder stage and CI both call this.
# Usage: build-fakeuid.sh <output .so path>
set -eu

if [ "$#" -ne 1 ]; then
  echo "usage: $0 <output .so path>" >&2
  exit 1
fi

src_dir=$(cd "$(dirname "$0")" && pwd)
gcc -shared -fPIC -O2 -Wall -Wextra -Werror "${src_dir}/fakeuid.c" -o "$1" -ldl
