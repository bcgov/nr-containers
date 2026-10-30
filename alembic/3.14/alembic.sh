#!/bin/bash
# Alembic helper script for common migration tasks
#
# Usage: ./alembic.sh --schema <schema_folder> <command> [options]
#
# Examples:
#   ./alembic.sh --schema THE status              # Show current migration status
#   ./alembic.sh --schema THE upgrade             # Apply all pending migrations
#   ./alembic.sh --schema THE upgrade-to 1.00020  # Runs all migrations up to V1.00020
#   ./alembic.sh --schema THE downgrade -1        # Rolls back a single version
#   ./alembic.sh --schema THE downgrade 1.00015   # Rolls back to version 1.00015
#
# ... --schema THE - This option refers to the migration folder (scripts/THE)
#                    and the database schema (THE).
# for `--schema DBA` - make sure you set the ORACLE_USER to a user with access to
#                      SYS to properly migrate these objects

set -e

# Script directory (where this script is located - should be repo root)
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="$REPO_ROOT/alembic/alembic.ini"

# Determine utils project path - works in container (/app/utils) and locally (../utils)
if [[ -d "/app/utils" ]]; then
    UTILS_PROJECT="/app/utils"
else
    UTILS_PROJECT="../utils"
fi

SCHEMA_FOLDER="THE" # default schema folder (and database schema) if not specified with --schema
DRY_RUN=0
STRICT=0
ARGS=()

# capture the args sent to the script
while [[ $# -gt 0 ]]; do
    case "$1" in
        -s|--schema)
            if [[ -z "$2" ]]; then
                echo "Schema name required after $1" >&2
                exit 1
            fi
            SCHEMA_FOLDER="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=1
            shift
            ;;
        --strict)
            STRICT=1
            shift
            ;;
        *)
            ARGS+=("$1")
            shift
            ;;
    esac
done

# Restore positional parameters without options
set -- "${ARGS[@]}"
# Convert schema folder to uppercase to match directory naming convention
SCHEMA_FOLDER="$(echo "$SCHEMA_FOLDER" | tr '[:lower:]' '[:upper:]')"
SCRIPTS_DIR="$REPO_ROOT/scripts/$SCHEMA_FOLDER"

echo "🚠: thank you for not choosing flyway"

# Set environment variables for Oracle connection
export ORACLE_SCHEMA_FOLDER="$SCHEMA_FOLDER"
export ORACLE_USER="${ORACLE_USER:-THE}"
export ORACLE_PASSWORD="${ORACLE_PASSWORD:-default}"
export ORACLE_HOST="${ORACLE_HOST:-localhost}"
export ORACLE_PORT="${ORACLE_PORT:-1525}"
export ORACLE_SERVICE="${ORACLE_SERVICE:-DBDOCK_01}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1" >&2
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

run_python() {
    if [[ -x "/app/utils/.venv/bin/python" ]]; then
        PYTHONPATH="$REPO_ROOT/alembic:$PYTHONPATH" /app/utils/.venv/bin/python "$@"
    else
        PYTHONPATH="$REPO_ROOT/alembic:$PYTHONPATH" uv --project "$UTILS_PROJECT" run python "$@"
    fi
}

run_alembic() {
    local extra_opts=()
    if [[ "$DRY_RUN" -eq 1 ]]; then
        extra_opts+=("-x" "dry_run=true")
        export ALEMBIC_DRY_RUN=1
    fi

    if [[ -x "/app/utils/.venv/bin/python" ]]; then
        /app/utils/.venv/bin/python -m alembic -c "$CONFIG_FILE" "${extra_opts[@]}" "$@"
    else
        uv --project "$UTILS_PROJECT" run python -m alembic -c "$CONFIG_FILE" "${extra_opts[@]}" "$@"
    fi
}

get_current_revision() {
    rev="$(run_alembic current 2>&1 \
        | sed -n -E 's/.*Current (DB )?revision: ([^[:space:]]+).*/\2/p' \
        | tail -1 || true)"
    if [[ "$rev" == "None" || "$rev" == "none" ]]; then
        rev=""
    fi
    echo "$rev"
}

print_pending_versions_only() {
    current_revision="$(get_current_revision)"
    run_python -m flyway_migration_name_validator list-pending --scripts-dir "$SCRIPTS_DIR" --current "$current_revision"
}


print_pending_versions() {
    print_pending_versions_only
}

print_pending_major_versions() {
    print_pending_versions | awk '{print $1}' | sed 's|\..*$||' | uniq
}


get_random_lebowski_quote() {
    if command -v python3 >/dev/null 2>&1; then
        python3 "$REPO_ROOT/alembic/lebowski_quotes.py"
    else
        run_python -m lebowski_quotes
    fi
}

print_dude_image() {
    local img_path="$REPO_ROOT/alembic/dude_abide.png"
    local ansi_path="$REPO_ROOT/alembic/dude_abide.ansi"
    if command -v timg >/dev/null 2>&1 && [[ -f "$img_path" ]]; then
        timg -p quarter -g 44x28 "$img_path"
    elif [[ -f "$ansi_path" ]]; then
        cat "$ansi_path"
    fi
}

print_usage() {
    echo ""
    print_dude_image
    local quote
    quote="$(get_random_lebowski_quote)"
    echo ""
    echo "  $quote"
    echo ""
    echo "--------------------------------------------------------------------------------"
    cat << 'EOF'
Alembic Migration Helper
--------------------------------------------------------------------------------

Usage: ./alembic.sh <command> [options]
    ./alembic.sh --schema <schema> <command> [options]

Note: Run this script from the repository root directory.

Options:
--------------------------------------------------------------------------------
  -s, --schema <schema> Target schema / migration folder (default: THE)
  --dry-run             Preview migrations to execute without applying changes to DB
  --strict              Fail (exit 1) instead of warning when upgrade-to targets a
                        version that does not exist on disk

Commands:
--------------------------------------------------------------------------------
  init                Initialize alembic_version table (run once first)
  status              Show current migration status
  upgrade [target]    Upgrade to target revision (default: head)
  upgrade-to <ver>    Upgrade to specific version (e.g., 1.100)
  upgrade-major <n>   Upgrade to the highest version in major <n> (e.g., 1 runs all 1.x)
  downgrade [-n]      Downgrade n steps (default: -1)
  baseline [target]   Baseline DB to target version without running scripts (default: head)
  repair              Repair migration metadata and align DB checksums with local files on disk
  help                Show this message

Examples:
--------------------------------------------------------------------------------
  # Check current state
  ./alembic.sh --schema THE status

  # Preview upgrade without applying changes (dry run)
  ./alembic.sh --schema THE upgrade --dry-run

  # Preview upgrade to a specific version number
  ./alembic.sh --schema THE upgrade-to 1.100 --dry-run

  # Upgrade to a specific version number (finds migration automatically)
  ./alembic.sh --schema THE upgrade-to 1.100

  # Upgrade to latest
  ./alembic.sh --schema THE upgrade

  # Preview downgrade one step without applying changes
  ./alembic.sh --schema THE downgrade -1 --dry-run

  # Downgrade one step
  ./alembic.sh --schema THE downgrade

  # Downgrade two steps
  ./alembic.sh --schema THE downgrade -2

  # Downgrade to a specific version
  ./alembic.sh --schema THE downgrade 1.092

  # Baseline a pre-existing database to latest (head)
  ./alembic.sh --schema THE baseline

  # Baseline a pre-existing database to a specific version
  ./alembic.sh --schema THE baseline 16.00096

  # Repair DB checksums to match modified local scripts
  ./alembic.sh --schema THE repair


Environment Variables:
--------------------------------------------------------------------------------
  SCHEMA_FOLDER      Target schema / migration folder (default: THE)
  ORACLE_USER        Database user (defaults to THE)
  ORACLE_PASSWORD    Database password (default: default)
  ORACLE_HOST        Database host (default: localhost)
  ORACLE_PORT        Database port (default: 1525)
  ORACLE_SERVICE     Database service (default: DBDOCK_01)
  DEBUG              Set to 1 to show full Python tracebacks on migration errors

EOF
}

# Change to alembic directory for commands to work correctly
cd "$REPO_ROOT/alembic"

if [ ! -d "$SCRIPTS_DIR" ]; then
    print_error "Schema migration directory not found: $SCRIPTS_DIR"
    exit 1
fi

case "${1:-help}" in

    status)
        print_info "Current migration revision:"
        current_output="$(run_alembic current 2>&1)"
        echo "$current_output"
        echo ""
        current_revision="$(get_current_revision)"
        pending_versions="$(run_python -m flyway_migration_name_validator list-pending --scripts-dir "$SCRIPTS_DIR" --current "$current_revision")"
        if [[ -n "$pending_versions" ]]; then
            print_info "Available unapplied versions:"
            pending_count="$(printf '%s\n' "$pending_versions" | wc -l | tr -d ' ')"
            printf '%s\n' "$pending_versions" | tail -20 | sed 's/^/  🚴 /'
            if [[ "$pending_count" -gt 20 ]]; then
                echo -e "${YELLOW}⚠️ 🦖${NC} (only showing last 20 of $pending_count pending migrations)"
            fi
        else
            print_success "No unapplied local versioned migrations"
        fi
        ;;

    upgrade)
        target="${2:-head}"
        if [[ "$DRY_RUN" -eq 1 ]]; then
            print_info "Upgrading to: $target (dry run)"
        else
            print_info "Upgrading to: $target"
        fi
        _tmpfile=$(mktemp)
        run_alembic upgrade "$target" 2>&1 | tee "$_tmpfile"
        upgrade_exit=${PIPESTATUS[0]}
        upgrade_output=$(cat "$_tmpfile")
        rm -f "$_tmpfile"

        if [[ $upgrade_exit -ne 0 ]]; then
            exit $upgrade_exit
        fi

        if printf '%s' "$upgrade_output" | grep -Eqi "No Revisions exist for:|Can't locate revision identified by"; then
            print_warning "Migration V${target} does not exist. No migrations were applied."
        elif [[ "$DRY_RUN" -eq 1 ]]; then
            print_success "Dry run complete for upgrade to $target (no changes applied)"
        else
            print_success "Upgraded to $target"
        fi
        ;;

    upgrade-major)
        if [ -z "$2" ]; then
            print_error "Major version number required. Usage: alembic.sh upgrade-major <major>"
            print_error "Example: alembic.sh upgrade-major 1"
            exit 1
        fi
        major="$2"
        # Find all migrations in this major version, sort by version, take the highest
        latest=$(find "$SCRIPTS_DIR" -type f -name "V${major}.*__*.sql" 2>/dev/null \
            | sed 's|.*/V||' | sed 's|__.*$||' | sort -t. -k1,1n -k2,2n | tail -1)

        if [ -z "$latest" ]; then
            print_info "scripts directory: $SCRIPTS_DIR"
            print_error "No migrations found for major version $major"
            print_info "Available unapplied major versions:"
            print_pending_major_versions
            exit 1
        fi

        print_info "Highest version in major $major: $latest"
        if [[ "$DRY_RUN" -eq 1 ]]; then
            print_info "Upgrading to: $latest (dry run)"
            run_alembic upgrade "$latest"
            print_success "Dry run complete for upgrade-major $major to $latest (no changes applied)"
        else
            print_info "Upgrading to: $latest"
            run_alembic upgrade "$latest"
            print_success "Upgraded to $latest"
        fi
        ;;


    upgrade-to)
        if [ -z "$2" ]; then
            print_error "Version number required. Usage: alembic.sh upgrade-to <version>"
            print_error "Example: alembic.sh upgrade-to 1.100"
            exit 1
        fi
        version="$2"
        matching=$(find "$SCRIPTS_DIR" -type f -name "V${version}__*.sql" 2>/dev/null | head -1)

        if [ -z "$matching" ]; then
            print_info "scripts directory: $SCRIPTS_DIR"
            if [[ "$STRICT" -eq 1 ]]; then
                # Under --strict a missing version is an error, not a no-op.
                # Callers such as migration_driver.sh resolve every version from
                # disk, so a miss means the plan and the scripts folder have
                # diverged. Exiting 0 here would let a rebuild skip an entire
                # segment and still report success.
                #
                # Deliberately avoids print_pending_versions: that needs a
                # database round trip, and this check runs before any
                # connection is required.
                print_error "Migration V${version} does not exist in $SCHEMA_FOLDER (--strict)."
                print_info "Run './alembic.sh --schema $SCHEMA_FOLDER status' to see available versions."
                exit 1
            fi
            print_warning "Migration V${version} does not exist. No migrations were applied."
            print_info "Available unapplied versions:"
            print_pending_versions | tail -20 || true
            exit 0
        fi

        revision_id="$version"
        print_info "Found migration: $(basename "$matching")"
        if [[ "$DRY_RUN" -eq 1 ]]; then
            print_info "Upgrading to: $revision_id (dry run)"
            run_alembic upgrade "$revision_id"
            print_success "Dry run complete for upgrade-to $revision_id (no changes applied)"
        else
            print_info "Upgrading to: $revision_id"
            run_alembic upgrade "$revision_id"
            print_success "Upgraded to $revision_id"
        fi
        ;;

    downgrade)
        target="${2:--1}"
        if [[ "$DRY_RUN" -eq 1 ]]; then
            print_info "Downgrading to: $target (dry run)"
            run_alembic downgrade "$target"
            print_success "Dry run complete for downgrade to $target (no changes applied)"
        else
            print_info "Downgrading to: $target"
            run_alembic downgrade "$target"
            print_success "Downgraded to $target"
        fi
        ;;

    baseline)
        target="${2:-head}"
        print_info "Baselining database to: $target"
        run_alembic stamp "$target"
        print_success "Baselined database to $target"
        ;;

    repair)
        print_info "Repairing migration metadata and aligning DB checksums with local files..."
        run_alembic -x verb=repair stamp current
        print_success "Repair complete"
        ;;

    help|--help|-h)
        print_usage
        ;;

    *)
        print_error "Unknown command: $1"
        echo ""
        print_usage
        exit 1
        ;;
esac
