#!/bin/sh
# Container entrypoint. When STORAGE_DIR points at a persistent volume (e.g. a Render disk),
# every runtime folder is kept there so uploads, reports, logs and the SQLite database
# survive redeploys. Without STORAGE_DIR the container behaves exactly as before.
set -e

if [ -n "$STORAGE_DIR" ]; then
    mkdir -p "$STORAGE_DIR"
    for name in Accounts data "cleaned data" reports logs; do
        target="$STORAGE_DIR/$name"
        mkdir -p "$target"
        if [ -d "/app/$name" ] && [ ! -L "/app/$name" ]; then
            # Seed the volume with anything the image ships, then swap the folder for a link
            cp -a "/app/$name/." "$target/" 2>/dev/null || true
            rm -rf "/app/$name"
        fi
        [ -L "/app/$name" ] || ln -s "$target" "/app/$name"
    done
    # Written by the pipeline on demand; a dangling link is fine until then
    [ -L /app/.last_cleaned_backup.json ] || ln -s "$STORAGE_DIR/.last_cleaned_backup.json" /app/.last_cleaned_backup.json

    # Keep the SQLite database on the volume unless a database server is configured
    if [ -z "$DATABASE_URL" ] && [ -z "$MYSQL_HOST" ]; then
        export DATABASE_URL="sqlite:///$STORAGE_DIR/agentic_ai_etl.db"
    fi
fi

exec "$@"
