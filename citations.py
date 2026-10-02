#!/usr/bin/env python3
"""Citation counts from NASA SciX (Science Explorer, ex-ADS) for the paper corpus.

    python citations.py status                      # token present? how many papers covered?
    python citations.py refresh                     # fetch never-seen papers + those older than 7 days
    python citations.py refresh --since 2026-09-01 --stale-days 1 --max-requests 50
    python citations.py refresh --all               # everything, ignoring freshness
    python citations.py top -n 30 [--since ... --until ...]

Needs a free SciX token in ``SCIX_API_TOKEN`` (or ``~/.scix/token``; ADS tokens still work):
https://scixplorer.org/user/settings/token
"""

from __future__ import annotations

import argparse
import sys

from core import citations, corpus, scix


def cmd_status(_args: argparse.Namespace) -> int:
    tok = scix.token()
    counts = citations.all_counts()
    n = corpus.stats().get('n', len(corpus.all_papers()))
    print(f'SciX token: {"configured" if tok else "MISSING (set SCIX_API_TOKEN)"}')
    print(f'papers in corpus: {n}; with a SciX record: {len(counts)}')
    if counts:
        cited = sum(1 for c in counts.values() if c['n'] > 0)
        newest = max(c['fetched'] for c in counts.values())
        print(f'cited at least once: {cited}; latest refresh: {newest}')
    stale = citations.stale_pids(7)
    print(f'due for refresh (never fetched or > 7 days): {len(stale)}')
    return 0 if tok else 1


def cmd_refresh(args: argparse.Namespace) -> int:
    if not scix.token():
        print('No SciX token (SCIX_API_TOKEN or ~/.scix/token); skipping citation refresh.')
        return 0 if args.quiet else 1
    pids = citations.stale_pids(0 if args.all else args.stale_days, args.since, args.until)
    if not pids:
        print('Citations are up to date.')
        return 0
    print(
        f'{len(pids)} paper(s) to refresh ({scix.CHUNK} per request, max {args.max_requests} requests)'
    )
    try:
        res = citations.refresh(pids, max_requests=args.max_requests)
    except scix.ScixError as exc:
        print(f'❌ {exc}')
        return 0 if args.quiet else 2
    print(
        f'✅ fetched {res["fetched"]} papers in {res["requests"]} request(s); '
        f'{res["found"]} known to SciX; {res["left"]} left for a later run'
        + (' (rate limited)' if res['rate_limited'] else '')
    )
    return 0


def cmd_top(args: argparse.Namespace) -> int:
    rows = citations.top(args.n, args.since, args.until)
    if not rows:
        print('No citation data yet (run `python citations.py refresh`).')
        return 0
    for r in rows:
        ref = ' (refereed)' if r['refereed'] else ''
        print(
            f'{r["citation_count"]:5d}  {r["report_date"]}  {r["pid"]:<11}  {r["title"][:80]}{ref}'
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('status', help='token and coverage').set_defaults(fn=cmd_status)
    r = sub.add_parser('refresh', help='fetch / update citation counts')
    r.add_argument('--since', help='only listing dates >= YYYY-MM-DD')
    r.add_argument('--until', help='only listing dates <= YYYY-MM-DD')
    r.add_argument(
        '--stale-days', type=float, default=7, help='re-fetch records older than this (default 7)'
    )
    r.add_argument('--all', action='store_true', help='refresh everything regardless of age')
    r.add_argument(
        '--max-requests', type=int, default=150, help='API call budget for this run (default 150)'
    )
    r.add_argument(
        '--quiet', action='store_true', help='exit 0 even without a token (for pipelines)'
    )
    r.set_defaults(fn=cmd_refresh)
    t = sub.add_parser('top', help='most cited papers')
    t.add_argument('-n', type=int, default=20)
    t.add_argument('--since')
    t.add_argument('--until')
    t.set_defaults(fn=cmd_top)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == '__main__':
    sys.exit(main())
