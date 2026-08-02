#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# OptimusDB — TPC-H loader.
#
# Builds electrum/tpch-dbgen inside a throwaway debian container, generates
# scale-factor-1 data, and bulk-loads it into the running Postgres container
# defined by project/docker-compose.yml.
#
# Usage:
#   bash load_tpch.sh              # SF=1 (default)
#   TPCH_SCALE=0.1 bash load_tpch.sh
#
# Idempotency:
#   - dbgen binary is reused if already built.
#   - .tbl files are reused if lineitem.tbl already exists.
#   - Schema is dropped + recreated every run (fast; TPC-H load is <2 min).
# -----------------------------------------------------------------------------
set -euo pipefail

# Git Bash on Windows rewrites Unix-looking args into Windows paths before
# they ever reach docker.exe — turning `-w /work` into `C:/Program Files/Git/work`.
# Kill that path-mangling for this script's lifetime.
export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL="*"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="$SCRIPT_DIR/tpch-build"
SQL_DIR="$SCRIPT_DIR/sql"
SCALE="${TPCH_SCALE:-1}"
CONTAINER="${PG_CONTAINER:-optimusdb-postgres}"
PG_USER="${PG_USER:-optimus}"
PG_DB="${PG_DB:-tpch}"
BUILDER_IMAGE="debian:12-slim"
TPCH_REPO="https://github.com/electrum/tpch-dbgen.git"

log() { printf '\n\033[1;36m[load_tpch]\033[0m %s\n' "$*"; }

# Docker Desktop on Windows wants bind-mount sources in Windows form (D:\...).
# On Linux/macOS, cygpath is missing and we return the path unchanged.
mount_path() {
    if command -v cygpath >/dev/null 2>&1; then
        cygpath -w "$1"
    else
        printf '%s\n' "$1"
    fi
}

# --- Pre-flight -------------------------------------------------------------
command -v docker >/dev/null || { echo "docker not found on PATH"; exit 1; }

if ! docker inspect -f '{{.State.Health.Status}}' "$CONTAINER" 2>/dev/null | grep -q healthy; then
    echo "Postgres container '$CONTAINER' is not healthy. Run 'docker compose up -d' first."
    exit 1
fi

mkdir -p "$BUILD_DIR"
BUILD_DIR_MOUNT="$(mount_path "$BUILD_DIR")"

# --- 1. Build dbgen ---------------------------------------------------------
if [[ ! -x "$BUILD_DIR/dbgen" ]]; then
    log "Building tpch-dbgen inside $BUILDER_IMAGE (one-time)..."
    docker run --rm \
        -v "${BUILD_DIR_MOUNT}:/work" \
        -w /work \
        "$BUILDER_IMAGE" bash -c '
            set -eu
            export DEBIAN_FRONTEND=noninteractive
            apt-get update -qq
            # libc6-dev pulls in <stdio.h> and friends — gcc alone lacks them on slim.
            apt-get install -y --no-install-recommends git make gcc libc6-dev ca-certificates >/dev/null
            if [ ! -d .git ]; then
                git clone --depth 1 '"$TPCH_REPO"' .
            fi
            make -s -e MACHINE=LINUX DATABASE=ORACLE WORKLOAD=TPCH CC=gcc
        '
else
    log "dbgen already built — skipping."
fi

# --- 2. Generate .tbl files -------------------------------------------------
if [[ ! -f "$BUILD_DIR/lineitem.tbl" ]]; then
    log "Generating TPC-H data at scale factor $SCALE..."
    docker run --rm \
        -v "${BUILD_DIR_MOUNT}:/work" \
        -w /work \
        "$BUILDER_IMAGE" bash -c "
            set -eu
            ./dbgen -s $SCALE -f
            # Postgres COPY chokes on the trailing '|' dbgen emits — strip it.
            sed -i 's/|\$//' *.tbl
        "
else
    log ".tbl files already present — skipping generation."
fi

# --- 3. Ship .tbl files into the Postgres container -------------------------
log "Copying .tbl files into $CONTAINER:/tmp/tpch/ ..."
docker exec "$CONTAINER" rm -rf /tmp/tpch
docker exec "$CONTAINER" mkdir -p /tmp/tpch
for tbl in region nation part supplier partsupp customer orders lineitem; do
    docker cp "$(mount_path "$BUILD_DIR/${tbl}.tbl")" "$CONTAINER:/tmp/tpch/${tbl}.tbl"
done

# --- 4. Create schema -------------------------------------------------------
log "Applying schema (01_schema.sql)..."
docker exec -i "$CONTAINER" psql -U "$PG_USER" -d "$PG_DB" -v ON_ERROR_STOP=1 -q < "$SQL_DIR/01_schema.sql"

# --- 5. Bulk load -----------------------------------------------------------
log "Loading data via server-side COPY..."
for tbl in region nation part supplier partsupp customer orders lineitem; do
    printf '  → %-8s ' "$tbl"
    docker exec "$CONTAINER" psql -U "$PG_USER" -d "$PG_DB" -q -c \
        "COPY $tbl FROM '/tmp/tpch/${tbl}.tbl' WITH (FORMAT text, DELIMITER '|');"
done

# --- 6. Keys, extension, ANALYZE --------------------------------------------
log "Applying primary keys, foreign keys, pg_stat_statements, ANALYZE (02_keys.sql)..."
docker exec -i "$CONTAINER" psql -U "$PG_USER" -d "$PG_DB" -v ON_ERROR_STOP=1 -q < "$SQL_DIR/02_keys.sql"

# --- 7. Summary -------------------------------------------------------------
log "Row counts:"
docker exec "$CONTAINER" psql -U "$PG_USER" -d "$PG_DB" -c "
    SELECT relname AS table_name,
           to_char(n_live_tup, 'FM999,999,999') AS rows
    FROM pg_stat_user_tables
    WHERE relname IN ('region','nation','part','supplier','partsupp','customer','orders','lineitem')
    ORDER BY n_live_tup;
"

log "Done. TPC-H SF=$SCALE loaded into $PG_DB."
