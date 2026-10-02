#!/usr/bin/env bash
# Backfill a range of listing days with the configured LLM backend (Claude CLI by default),
# then rebuild the site and the wiki once. Safe to re-run: days that already have a real digest
# are skipped (index-only reports from prefetch.py are regenerated), and a day that fails
# (arXiv HTTP 429 cooldown, LLM unavailable) is retried after a pause.
# Exit codes: 0 = done, 2 = aborted because one day failed 4 times in a row (likely an LLM usage limit).
#
#   ./backfill.sh 2026-09-01 2026-09-25            # every weekday in the range
#   nohup ./backfill.sh 2026-09-01 2026-09-25 > reports/backfill.log 2>&1 &   # survives closing the laptop
set -uo pipefail
source "$(dirname "$0")/env.sh"
cd "$HERE"
start="${1:?start date YYYY-MM-DD}"; end="${2:?end date YYYY-MM-DD}"
has_digest() { [[ -f "reports/arXiv_astro_ph_HE_daily_report_$1.html" ]] && ! grep -qF '<!-- index-only -->' "reports/fragments/$1.html" 2>/dev/null; }
rebuild() {
  "$PY" build_site.py
  for w in $("$PY" -c "
import datetime,sys
a=datetime.date.fromisoformat('$start'); b=datetime.date.fromisoformat('$end'); seen=[]
while a<=b:
    y,w,_=a.isocalendar(); k=f'{y}-W{w:02d}'
    if k not in seen: seen.append(k)
    a+=datetime.timedelta(days=1)
print(' '.join(seen))"); do "$PY" wiki.py fold --week "$w" >/dev/null; done
  "$PY" wiki.py build; "$PY" wiki.py html; "$PY" wiki.py lint --strict || true
}
aborted=0
d="$start"
while [[ "$d" < "$end" || "$d" == "$end" ]]; do
  dow=$(date -d "$d" +%u)
  if (( dow <= 5 )); then
    if has_digest "$d"; then
      echo "⏭️  $d already has a digest"
    else
      ok=0
      for attempt in 1 2 3 4; do
        echo "▶️  $d (attempt $attempt) $(date '+%H:%M')"
        out=$("$PY" report.py --date "$d" 2>&1); rc=$?; printf '%s\n' "$out"
        if [[ $rc -eq 0 ]] && { has_digest "$d" || grep -q "No new papers" <<<"$out"; }; then ok=1; break; fi
        echo "⏳ $d failed; waiting 31 min before retrying (arXiv cooldown / LLM limit)"; sleep 1860
      done
      if (( ok == 0 )); then echo "❌ $d failed 4 times; aborting this run (will be retried by a later pass)"; aborted=1; break; fi
    fi
  fi
  d=$(date -d "$d + 1 day" +%F)
done
rebuild
if (( aborted )); then echo "⚠️  backfill aborted at $d $(date '+%F %H:%M')"; exit 2; fi
echo "✅ backfill finished $(date '+%F %H:%M')"
