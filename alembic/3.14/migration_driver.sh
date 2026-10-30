#!/bin/bash
# Shared driver for the cross-schema migration runners (issue #787).
#
# Sourced by run_all_migrations.sh and run_timestamp_migrations.sh. Both do the
# same thing and differ only in which layer of the plan they execute:
#
#   1. Ask alembic/migration_plan.py for an ordered list of execution segments.
#   2. Run each segment as the correct Oracle user, in the order given.
#
# A segment is a contiguous run of migrations in one schema. Because the plan is
# globally ordered, consecutive segments routinely switch schemas - that is the
# entire point, and is what lets a change set interleave across schema
# boundaries. See docs/cross_schema_migration_plan.md.

GREEN='\033[0;32m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -d "/app/utils" ]]; then
	UTILS_PROJECT="/app/utils"
else
	UTILS_PROJECT="$REPO_ROOT/utils"
fi

say() {
	echo -e "${GREEN}▶${NC} $1"
}

say_error() {
	echo -e "${RED}✗${NC} $1" >&2
}

say_segment() {
	echo -e "${BLUE}→${NC} $1"
}

# Run a python module with alembic/ on the path, preferring the container's
# pre-built venv and falling back to uv locally. Mirrors alembic.sh::run_python.
run_python() {
	if [[ -x "/app/utils/.venv/bin/python" ]]; then
		PYTHONPATH="$REPO_ROOT/alembic:${PYTHONPATH:-}" /app/utils/.venv/bin/python "$@"
	else
		PYTHONPATH="$REPO_ROOT/alembic:${PYTHONPATH:-}" uv --project "$UTILS_PROJECT" run python "$@"
	fi
}

# Execute one layer of the migration plan.
#
# $1 - layer: baseline | timestamps | all
# $2 - run grants: true | false (baseline grant segments are skipped when false)
run_migration_plan() {
	local layer="$1"
	local run_grants="${2:-true}"
	local plan_args=(-m migration_plan --layer "$layer" --format tsv)

	if [[ "$run_grants" != true ]]; then
		plan_args+=(--no-grants)
	fi

	say "Building the global cross-schema execution plan (layer: $layer)..."

	# Capture the plan before executing anything. Generating it is a pure,
	# offline operation, so any ordering or numbering problem surfaces here -
	# before a single statement has been applied to the database.
	local plan
	if ! plan="$(run_python "${plan_args[@]}")"; then
		say_error "Could not build the migration plan. No migrations were applied."
		return 1
	fi

	if [[ -z "$plan" ]]; then
		say "No migrations to apply for layer '$layer'"
		return 0
	fi

	local segment_count
	segment_count="$(printf '%s\n' "$plan" | wc -l | tr -d ' ')"
	say "Plan resolved to $segment_count segment(s)"

	local user schema version seg_layer index=0
	while IFS=$'\t' read -r user schema version seg_layer; do
		[[ -z "$user" ]] && continue
		index=$((index + 1))
		say_segment "[$index/$segment_count] $schema → V$version (as $user, $seg_layer)"

		if ! ORACLE_USER="$user" "$REPO_ROOT/alembic.sh" \
			--schema "$schema" upgrade-to "$version" --strict; then
			say_error "Segment $index/$segment_count failed: $schema → V$version"
			return 1
		fi
	done < <(printf '%s\n' "$plan")

	say "Completed $segment_count segment(s) for layer '$layer'"
}
