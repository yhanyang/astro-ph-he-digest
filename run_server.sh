#!/usr/bin/env bash
# Start the FastAPI web UI on http://${HOST:-127.0.0.1}:${PORT:-8080} (HOST / ALLOWED_NETS / UI_TOKEN: see env.sh)
set -euo pipefail
source "$(dirname "$0")/env.sh"
cd "$HERE"
exec "$PY" -m uvicorn server:app --host "${HOST:-127.0.0.1}" --port "${PORT:-8080}"
