#!/usr/bin/env bash
# Shared entrypoint for the api image. The API container runs DB migrations
# before serving; worker/beat/browser-worker skip migrations (the api owns them)
# to avoid concurrent-migration races.
set -euo pipefail

if [ "${1:-}" = "uvicorn" ]; then
    python -m app.prestart
fi

exec "$@"
