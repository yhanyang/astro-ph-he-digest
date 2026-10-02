#!/usr/bin/env bash
# Weekday scheduler for the daily pipeline (report → citations → site → wiki).
#
#   setsid nohup ./scheduler.sh > /dev/null 2>&1 &   # start in the background (survives logout)
#   ./scheduler.sh --now                              # run the pipeline once right away, then keep scheduling
#   ./scheduler.sh --dry-run                          # only print the next run time
#   pkill -f scheduler.sh                             # stop
#
# arXiv announces Sun–Thu at 20:00 ET (02:00 Europe/Rome the next morning); the listing is
# dated that next day, so the pipeline runs Mon–Fri at RUN_AT local time (default 05:00).
# A failed run (network, arXiv 429, LLM error) is retried every RETRY_WAIT seconds, up to
# RETRIES times. With KEEP_SERVER=1 (default) the web UI is (re)started if it is not listening.
# Logs: reports/scheduler.log (this script) and reports/daily-YYYY-MM-DD.log (pipeline output).
set -uo pipefail
source "$(dirname "$0")/env.sh"
cd "$HERE"

RUN_AT="${RUN_AT:-05:00}"                 # HH:MM, local time of TZ_LOCAL
TZ_LOCAL="${TZ_LOCAL:-Europe/Rome}"
RETRIES="${RETRIES:-4}"
RETRY_WAIT="${RETRY_WAIT:-1800}"
KEEP_SERVER="${KEEP_SERVER:-1}"
PORT="${PORT:-8080}"
LOG="reports/scheduler.log"
LOCK="reports/.scheduler.lock"

log() { printf '%s  %s\n' "$(TZ=$TZ_LOCAL date '+%F %T')" "$*" | tee -a "$LOG"; }

next_run_ts() {
    # Epoch seconds of the next Mon–Fri RUN_AT strictly after now.
    local now d day dow ts
    now=$(date +%s)
    for d in 0 1 2 3 4 5 6 7; do
        day=$(TZ=$TZ_LOCAL date -d "+$d day" +%F)
        dow=$(TZ=$TZ_LOCAL date -d "$day" +%u)
        [ "$dow" -le 5 ] || continue
        ts=$(TZ=$TZ_LOCAL date -d "$day $RUN_AT" +%s)
        if [ "$ts" -gt "$now" ]; then echo "$ts"; return 0; fi
    done
    return 1
}

ensure_server() {
    [ "$KEEP_SERVER" = "1" ] || return 0
    if ! ss -ltn 2>/dev/null | grep -q ":${PORT} "; then
        log "web UI not listening on :$PORT — starting run_server.sh"
        nohup ./run_server.sh >> reports/server.log 2>&1 &
        sleep 3
    fi
}

run_pipeline() {
    local attempt=1 day
    day=$(TZ=$TZ_LOCAL date +%F)
    while :; do
        log "run_report.sh starting (attempt $attempt/$((RETRIES + 1)))"
        if ./run_report.sh >> "reports/daily-$day.log" 2>&1; then
            log "pipeline finished OK — see reports/daily-$day.log"
            return 0
        fi
        log "pipeline FAILED (exit $?) — see reports/daily-$day.log"
        [ "$attempt" -le "$RETRIES" ] || { log "giving up for today"; return 1; }
        attempt=$((attempt + 1))
        log "retrying in $((RETRY_WAIT / 60)) min"
        sleep "$RETRY_WAIT"
    done
}

if [ "${1:-}" = "--dry-run" ]; then
    ts=$(next_run_ts) && echo "next run: $(TZ=$TZ_LOCAL date -d "@$ts" '+%a %F %T %Z') (in $(( (ts - $(date +%s)) / 60 )) min)"
    exit 0
fi

# one scheduler at a time
exec 9>"$LOCK"
if ! flock -n 9; then
    echo "scheduler.sh is already running (lock $LOCK)"; exit 1
fi

trap 'log "scheduler stopped"; exit 0' INT TERM
log "scheduler started (pid $$): Mon–Fri at $RUN_AT $TZ_LOCAL, retries=$RETRIES every $((RETRY_WAIT / 60)) min"
ensure_server
if [ "${1:-}" = "--now" ]; then run_pipeline; fi

while :; do
    ts=$(next_run_ts) || { log "cannot compute next run"; sleep 3600; continue; }
    log "next run: $(TZ=$TZ_LOCAL date -d "@$ts" '+%a %F %T')"
    # sleep in short slices so clock changes / suspends are picked up
    while [ "$(date +%s)" -lt "$ts" ]; do
        remaining=$(( ts - $(date +%s) ))
        sleep $(( remaining < 900 ? remaining : 900 ))
        ensure_server
    done
    run_pipeline
    sleep 120   # make sure we are past RUN_AT before computing the next slot
done
