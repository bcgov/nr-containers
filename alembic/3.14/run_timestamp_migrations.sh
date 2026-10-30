#!/bin/bash

# - Run any timestamped migrations, across all schemas, in true global order.
#
#   Kept separate from run_all_migrations.sh because sometimes we only want to
#   run the original data that came out of the original database extraction.
#
#   This script used to drain one schema at a time (all of DBA, then all of
#   THE, ...). That is not the order the migrations were authored in: merge.yml
#   stamps every file in a merged PR with one shared timestamp major and keeps
#   the author's minors, so ordering is expressed across schemas, not within
#   them. Draining per schema silently reordered those changes. The plan built
#   by alembic/migration_plan.py restores the authored order.
#
#   See docs/cross_schema_migration_plan.md and issue #787.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=migration_driver.sh
source "$SCRIPT_DIR/migration_driver.sh"

usage() {
	echo "Usage: $0 [-h|--help]"
}

if [[ $# -gt 0 ]]; then
	case "$1" in
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
fi

run_migration_plan timestamps

say "Completed all available migrations"
