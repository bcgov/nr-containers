#!/bin/bash
# Fails when tracked files use a CodeQL-supported language that has no
# matrix entry in the CodeQL workflow.
# Usage: codeql-coverage.sh <repo dir> <codeql workflow path>
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "usage: $0 <repo dir> <codeql workflow path>" >&2
  exit 1
fi
repo=$1
workflow=$2

# Language a tracked path belongs to, or nothing
language_of() {
  case "$1" in
    .github/workflows/*.yml | .github/workflows/*.yaml | action.yml | action.yaml | */action.yml | */action.yaml) echo actions ;;
    *.c | *.h | *.cc | *.cpp | *.cxx | *.hh | *.hpp | *.hxx) echo c-cpp ;;
    *.cs | *.cshtml | *.razor) echo csharp ;;
    *.go) echo go ;;
    *.java | *.kt | *.kts) echo java-kotlin ;;
    *.js | *.jsx | *.mjs | *.cjs | *.ts | *.tsx | *.mts | *.cts) echo javascript-typescript ;;
    *.py) echo python ;;
    *.rb | *.erb | Gemfile | */Gemfile) echo ruby ;;
    *.swift) echo swift ;;
    *.rs) echo rust ;;
  esac
}

mapfile -t present < <(git -C "${repo}" ls-files | while read -r f; do language_of "${f}"; done | sort -u)
mapfile -t configured < <(yq -r '.jobs[].strategy.matrix.include[]?.language' "${workflow}" | sort -u)

echo "Languages in repo: ${present[*]:-none}"
echo "Languages in ${workflow}: ${configured[*]:-none}"

missing=$(comm -23 <(printf '%s\n' "${present[@]}") <(printf '%s\n' "${configured[@]}") | grep -v '^$' || true)
if [ -n "${missing}" ]; then
  for l in ${missing}; do
    echo "::error::CodeQL-supported language '${l}' has files but no matrix entry in ${workflow}"
  done
  exit 1
fi
echo "All CodeQL-supported languages are covered."
