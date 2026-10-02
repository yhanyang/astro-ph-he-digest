#!/usr/bin/env bash
# Generate the daily report, rebuild the static site, then sync and lint the Obsidian wiki.
#   ./run_report.sh                 # latest arXiv announcement
#   ./run_report.sh --date 2026-09-30
set -euo pipefail
source "$(dirname "$0")/env.sh"
cd "$HERE"
"$PY" report.py "$@"
# SciX (ex-ADS) citation counts (optional: needs SCIX_API_TOKEN; never fails the run).
"$PY" citations.py refresh --quiet --max-requests 60 || true
"$PY" build_site.py
# Knowledge base (claude-obsidian style): idempotent build, weekly rollup, health check.
"$PY" wiki.py fold   # weekly rollup first so Home can link it
"$PY" wiki.py build
"$PY" wiki.py html   # HTML export of the wiki, linked with the reports
"$PY" wiki.py lint --strict || echo "⚠️  wiki lint found problems (see above); report itself is fine."
