#!/bin/bash

# - Run the extracted baseline migrations across every schema.
#
#   The execution order is no longer hardcoded here. It is declared in
#   alembic/baseline_order.json and resolved by alembic/migration_plan.py, which
#   also asserts that every baseline migration file on disk is claimed by
#   exactly one segment. Previously this script pinned each schema to a major
#   version by hand, which meant a newly added major was silently never applied.
#
#   See docs/cross_schema_migration_plan.md and issue #787.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=migration_driver.sh
source "$SCRIPT_DIR/migration_driver.sh"

RUN_GRANTS=true

usage() {
	echo "Usage: $0 [--no-grants] [-h|--help]"
	echo ""
	echo "  --no-grants   Skip the grant segments of the baseline"
}

while [[ $# -gt 0 ]]; do
	case "$1" in
		--no-grants)
			RUN_GRANTS=false
			;;
		-h|--help)
			usage
			exit 0
			;;
		*)
			echo "Unknown option: $1" >&2
			usage >&2
			exit 1
			;;
	esac
	shift
done

if [[ "$RUN_GRANTS" != true ]]; then
	say "Skipping grants (--no-grants)"
fi

run_migration_plan baseline "$RUN_GRANTS"

say "Completed all available migrations"
