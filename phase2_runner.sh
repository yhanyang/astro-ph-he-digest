#!/usr/bin/env bash
# Phase-2 runner: wait until prefetch.py has finished, then backfill real digests month by month
# (newest month first) with the configured LLM backend, repeating passes until no index-only day
# is left in the range. Designed for `setsid nohup ./phase2_runner.sh FROM TO > reports/phase2.log 2>&1 &`.
set -uo pipefail
source "$(dirname "$0")/env.sh"
cd "$HERE"
FROM="${1:-2026-01-01}"; TO="${2:-2026-07-31}"
log() { echo "$(date '+%F %T')  $*"; }
remaining() {
  "$PY" - "$FROM" "$TO" <<'PY'
import sys, glob, os
a, b = sys.argv[1], sys.argv[2]
print(sum(1 for f in glob.glob('reports/fragments/*.html')
          if a <= os.path.basename(f)[:-5] <= b and '<!-- index-only -->' in open(f, encoding='utf-8').read()))
PY
}
months() {  # "first last" per month in the range, newest month first
  "$PY" - "$FROM" "$TO" <<'PY'
import sys, datetime, calendar
a = datetime.date.fromisoformat(sys.argv[1]); b = datetime.date.fromisoformat(sys.argv[2])
keys = []
d = b
while d >= a:
    k = d.strftime('%Y-%m')
    if k not in keys: keys.append(k)
    d -= datetime.timedelta(days=1)
for k in keys:
    y, m = map(int, k.split('-'))
    print(max(a, datetime.date(y, m, 1)), min(b, datetime.date(y, m, calendar.monthrange(y, m)[1])))
PY
}
log "waiting for prefetch.py to finish"
while pgrep -f "prefetch.py" >/dev/null; do sleep 120; done
log "prefetch finished; phase 2 for $FROM .. $TO, $(remaining) index-only day(s) to digest"
for pass in 1 2 3 4 5 6 7 8; do
  left=$(remaining); log "pass $pass: $left index-only day(s) left"
  [[ "$left" -eq 0 ]] && break
  while read -r first last; do
    [[ "$(remaining)" -eq 0 ]] && break
    log "backfill $first .. $last"
    ./backfill.sh "$first" "$last" >> "reports/backfill-${first:0:7}.log" 2>&1; rc=$?
    log "backfill $first .. $last finished (rc=$rc, $(remaining) index-only day(s) left overall)"
    if [[ $rc -eq 2 ]]; then log "LLM unavailable (usage limit?) — sleeping 2 h before continuing"; sleep 7200; fi
    sleep 60
  done < <(months)
done
log "phase 2 finished: $(remaining) index-only day(s) remain in $FROM .. $TO"
