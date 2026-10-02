"""Slow, resumable backfill of listing days: fetch (rate-limit aware) and, optionally,
write index-only reports so the site, wiki and search cover the range without an LLM.

    nohup .venv/bin/python prefetch.py --from 2026-01-01 --to 2026-07-31 --index-only > reports/prefetch.log 2>&1 &

Newest day first. A day that already has a real digest is left alone; a cached day is not
fetched again; an index-only report is only written where no digest exists. Every
``--rebuild-every`` processed days (and at the end) the static site and the wiki are rebuilt.
"""

from __future__ import annotations

import argparse
import datetime
import os
import sys
import time

from core import corpus
from core.fetcher import (
    ARXIV_COOLDOWN_PATH,
    ARXIV_TZ,
    _cache_path,
    fetch_arxiv_papers,
    get_arxiv_sync_window,
)
from core.indexonly import PROVIDER, build_fragment, focus_count, is_index_only
from core.render import FRAGMENTS_DIR, save_html


def _log(msg: str) -> None:
    print(f'{datetime.datetime.now():%Y-%m-%d %H:%M:%S}  {msg}', flush=True)


def _as_of(date: datetime.date) -> datetime.datetime:
    return ARXIV_TZ.localize(datetime.datetime.combine(date, datetime.time(hour=12)))


def _cooldown_wait() -> float:
    try:
        with open(ARXIV_COOLDOWN_PATH) as f:
            return max(0.0, float(f.read().strip()) - time.time())
    except (OSError, ValueError):
        return 0.0


def _fetch_with_backoff(date: datetime.date, max_tries: int = 6) -> list[dict] | None:
    for attempt in range(1, max_tries + 1):
        wait = _cooldown_wait()
        if wait > 0:
            _log(f'   arXiv cooldown active, sleeping {int(wait) + 30}s')
            time.sleep(wait + 30)
        try:
            return fetch_arxiv_papers(as_of=_as_of(date))
        except (
            Exception
        ) as exc:  # 429 -> cooldown was set by the fetcher; anything else: retry a few times
            msg = str(exc)
            _log(f'   fetch failed ({attempt}/{max_tries}): {msg[:120]}')
            if '429' not in msg and 'cooldown' not in msg.lower():
                time.sleep(60 * attempt)
    return None


def _rebuild(weeks: set[str]) -> None:
    import build_site
    from core import wiki

    _log(f'rebuilding site + wiki ({len(weeks)} weeks to fold)')
    build_site.build()
    for w in sorted(weeks):
        wiki.fold(w)
    wiki.Build().run()
    wiki.export_html()
    _log('rebuild done')


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument('--from', dest='start', required=True, help='first listing date YYYY-MM-DD')
    ap.add_argument('--to', dest='end', required=True, help='last listing date YYYY-MM-DD')
    ap.add_argument(
        '--interval',
        type=float,
        default=75.0,
        help='seconds between two arXiv requests (default 75)',
    )
    ap.add_argument(
        '--index-only',
        action='store_true',
        help='write index-only reports for days without a digest',
    )
    ap.add_argument(
        '--rebuild-every',
        type=int,
        default=20,
        help='rebuild site + wiki every N processed days (0 = only at the end)',
    )
    ap.add_argument(
        '--oldest-first',
        action='store_true',
        help='process in chronological order (default: newest first)',
    )
    a = ap.parse_args()

    start, end = datetime.date.fromisoformat(a.start), datetime.date.fromisoformat(a.end)
    days = [start + datetime.timedelta(days=i) for i in range((end - start).days + 1)]
    days = [d for d in days if d.weekday() < 5]
    if not a.oldest_first:
        days.reverse()
    _log(
        f'{len(days)} listing days {days[-1] if not a.oldest_first else days[0]} .. {days[0] if not a.oldest_first else days[-1]}, interval {a.interval:.0f}s'
    )

    processed = 0
    touched_weeks: set[str] = set()
    for d in days:
        iso = d.isoformat()
        frag_path = os.path.join(FRAGMENTS_DIR, f'{iso}.html')
        if os.path.exists(frag_path):
            with open(frag_path, encoding='utf-8') as f:
                if not is_index_only(f.read()):
                    _log(f'{iso}: digest exists, skip')
                    continue
        start_t, end_t = get_arxiv_sync_window(as_of=_as_of(d))
        cached = os.path.exists(_cache_path(start_t, end_t))
        papers = _fetch_with_backoff(d)
        if papers is None:
            _log(f'{iso}: FAILED to fetch after retries; continuing')
            continue
        if not papers:
            _log(f'{iso}: no papers (holiday / empty window)')
        elif a.index_only:
            save_html(papers, build_fragment(papers), PROVIDER, as_of=_as_of(d))
            added = corpus.upsert_papers(papers, iso)
            y, w, _ = d.isocalendar()
            touched_weeks.add(f'{y}-W{w:02d}')
            processed += 1
            _log(
                f'{iso}: {len(papers)} papers cached, index-only report written '
                f'({focus_count(papers)} keyword-focus), corpus +{added}'
            )
        else:
            _log(f'{iso}: {len(papers)} papers cached')
        if a.rebuild_every and processed and processed % a.rebuild_every == 0:
            _rebuild(touched_weeks)
        if not cached:
            time.sleep(a.interval)
    if processed:
        _rebuild(touched_weeks)
    _log(f'done: {processed} index-only days written; corpus now {corpus.stats()["n"]} papers')
    return 0


if __name__ == '__main__':
    sys.exit(main())
