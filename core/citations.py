"""Citation counts from NASA SciX (ex-ADS), cached in ``data/papers.db`` (table ``citations``).

Counts are shown as a badge on every paper entry, as "Most cited" lists in the week / month /
year summaries and the wiki, and are refreshed incrementally by ``python citations.py refresh``.
"""

from __future__ import annotations

import datetime
import sqlite3
import time

from core import corpus, scix

_SCHEMA = """
CREATE TABLE IF NOT EXISTS citations (
    pid            TEXT PRIMARY KEY,
    bibcode        TEXT NOT NULL DEFAULT '',
    citation_count INTEGER NOT NULL DEFAULT 0,
    read_count     INTEGER NOT NULL DEFAULT 0,
    refereed       INTEGER NOT NULL DEFAULT 0,
    pubdate        TEXT NOT NULL DEFAULT '',
    pub            TEXT NOT NULL DEFAULT '',
    found          INTEGER NOT NULL DEFAULT 1,
    fetched_ts     REAL NOT NULL
);
"""


def _connect() -> sqlite3.Connection:
    conn = corpus._connect()
    conn.executescript(_SCHEMA)
    return conn


def all_counts() -> dict[str, dict]:
    """``{pid: {'n': citations, 'bibcode': ..., 'refereed': bool, 'pub': ..., 'fetched': 'YYYY-MM-DD'}}``
    for every paper SciX knows about."""
    with _connect() as conn:
        rows = conn.execute(
            'SELECT pid, bibcode, citation_count, read_count, refereed, pub, fetched_ts '
            'FROM citations WHERE found = 1'
        ).fetchall()
    return {
        r['pid']: {
            'n': r['citation_count'],
            'reads': r['read_count'],
            'bibcode': r['bibcode'],
            'refereed': bool(r['refereed']),
            'pub': r['pub'],
            'fetched': datetime.date.fromtimestamp(r['fetched_ts']).isoformat(),
        }
        for r in rows
    }


def scix_url(bibcode: str) -> str:
    return scix.ABS_URL.format(bibcode=bibcode)


def stale_pids(
    stale_days: float = 7, since: str | None = None, until: str | None = None
) -> list[str]:
    """Corpus pids never fetched or fetched more than ``stale_days`` ago (never-fetched first,
    then the oldest fetch), optionally limited to listing dates in ``[since, until]``."""
    cutoff = time.time() - stale_days * 86400
    with _connect() as conn:
        rows = conn.execute(
            'SELECT p.pid, p.report_date, c.fetched_ts FROM papers p '
            'LEFT JOIN citations c ON c.pid = p.pid '
            'WHERE (c.pid IS NULL OR c.fetched_ts < ?) '
            'AND (? IS NULL OR p.report_date >= ?) AND (? IS NULL OR p.report_date <= ?) '
            'ORDER BY c.fetched_ts IS NOT NULL, c.fetched_ts, p.report_date DESC',
            (cutoff, since, since, until, until),
        ).fetchall()
    return [r['pid'] for r in rows]


def store(records: dict[str, dict], missing: list[str]) -> None:
    """Upsert SciX records; ``missing`` ids are remembered as not (yet) in SciX."""
    now = time.time()
    with _connect() as conn:
        for pid, r in records.items():
            conn.execute(
                'INSERT INTO citations (pid, bibcode, citation_count, read_count, refereed, pubdate, '
                'pub, found, fetched_ts) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?) '
                'ON CONFLICT(pid) DO UPDATE SET bibcode = excluded.bibcode, '
                'citation_count = excluded.citation_count, read_count = excluded.read_count, '
                'refereed = excluded.refereed, pubdate = excluded.pubdate, pub = excluded.pub, '
                'found = 1, fetched_ts = excluded.fetched_ts',
                (
                    pid,
                    r.get('bibcode', ''),
                    int(r.get('citation_count') or 0),
                    int(r.get('read_count') or 0),
                    1 if r.get('refereed') else 0,
                    r.get('pubdate', ''),
                    r.get('pub', ''),
                    now,
                ),
            )
        for pid in missing:
            conn.execute(
                'INSERT INTO citations (pid, found, fetched_ts) VALUES (?, 0, ?) '
                'ON CONFLICT(pid) DO UPDATE SET fetched_ts = excluded.fetched_ts',
                (pid, now),
            )


def refresh(pids: list[str], max_requests: int = 150, token: str | None = None, log=print) -> dict:
    """Fetch SciX records for ``pids`` (at most ``max_requests`` API calls) and store them.

    Returns ``{'fetched': n, 'found': n, 'requests': n, 'rate_limited': bool, 'left': n}``.
    """
    budget = max_requests * scix.CHUNK
    todo, left = pids[:budget], pids[budget:]
    found = 0
    rate_limited = False
    done = 0
    for start in range(0, len(todo), scix.CHUNK):
        chunk = todo[start : start + scix.CHUNK]
        try:
            recs = scix.query_arxiv_ids(chunk, token)
        except scix.ScixRateLimit as exc:
            rate_limited = True
            when = (
                datetime.datetime.fromtimestamp(exc.reset_ts).strftime('%Y-%m-%d %H:%M')
                if exc.reset_ts
                else 'later'
            )
            log(f'⏳ SciX rate limit reached; retry after {when}.')
            left = todo[start:] + left
            break
        store(recs, [p for p in chunk if p not in recs])
        found += len(recs)
        done += len(chunk)
    return {
        'fetched': done,
        'found': found,
        'requests': (done + scix.CHUNK - 1) // scix.CHUNK,
        'rate_limited': rate_limited,
        'left': len(left),
    }


def top(n: int = 20, since: str | None = None, until: str | None = None) -> list[dict]:
    """Most cited corpus papers (joined with their listing data)."""
    with _connect() as conn:
        rows = conn.execute(
            'SELECT p.*, c.citation_count, c.bibcode, c.refereed, c.pub FROM citations c '
            'JOIN papers p ON p.pid = c.pid WHERE c.found = 1 AND c.citation_count > 0 '
            'AND (? IS NULL OR p.report_date >= ?) AND (? IS NULL OR p.report_date <= ?) '
            'ORDER BY c.citation_count DESC, p.report_date DESC LIMIT ?',
            (since, since, until, until, n),
        ).fetchall()
    return [dict(r) for r in rows]
