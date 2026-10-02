"""Persistent paper corpus accumulated across daily runs.

Ported from the ``arxiv_daemon.py`` / ``aslite/db.py`` idea in
karpathy/arxiv-sanity-lite: every fetched paper is kept in a local SQLite
database so that search, similarity and recommendations can span all the days
this instance has ever seen, not just today's listing.

Each row remembers the listing date and the ``[N]`` number the paper carried
in that day's report, so hits can deep-link back to ``/r/<date>#pN``.
"""

import datetime
import glob
import json
import os
import re
import sqlite3
import time

from core.config import REPORTS_DIR

# Corpus location: SANITY_DATA_DIR, else <REPORTS_DIR>/.data when that layout exists (the
# content repo / gh-pages layout, everything generated in one directory), else ./data.
DATA_DIR = os.getenv('SANITY_DATA_DIR') or (
    os.path.join(REPORTS_DIR, '.data')
    if os.path.isdir(os.path.join(REPORTS_DIR, '.data'))
    else './data'
)
DB_PATH = os.path.join(DATA_DIR, 'papers.db')

_ARXIV_ID_RE = re.compile(r'/abs/([^/?#]+?)(?:v\d+)?/?(?:[?#]|$)')
_CACHE_NAME_RE = re.compile(r'arxiv_(\d{8})T\d{4}_(\d{8})T\d{4}\.json$')

_SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    pid         TEXT PRIMARY KEY,
    version     TEXT,
    title       TEXT NOT NULL,
    authors     TEXT NOT NULL,
    summary     TEXT NOT NULL,
    url         TEXT NOT NULL,
    pdf_url     TEXT,
    categories  TEXT NOT NULL,
    comment     TEXT,
    journal_ref TEXT,
    doi         TEXT,
    report_date TEXT NOT NULL,
    number      INTEGER NOT NULL,
    added_ts    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_papers_report_date ON papers(report_date);
"""


def arxiv_pid(url: str) -> str | None:
    """Bare arXiv identifier (no version) from an abs URL, e.g. ``2609.38341``."""
    m = _ARXIV_ID_RE.search(url or '')
    return m.group(1) if m else None


def arxiv_version(url: str) -> str:
    """Version suffix of an abs URL (``v1``), or ``''`` when absent."""
    m = re.search(r'(v\d+)/?(?:[?#]|$)', url or '')
    return m.group(1) if m else ''


def _connect() -> sqlite3.Connection:
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def _row_to_paper(row: sqlite3.Row) -> dict:
    p = dict(row)
    p['categories'] = json.loads(p['categories'] or '[]')
    return p


def upsert_papers(papers: list[dict], report_date: str) -> int:
    """Insert or refresh ``papers`` (in report order) under ``report_date``.

    Returns the number of rows that were new. Existing rows keep their
    original ``added_ts`` but take the latest metadata (journal_ref, doi, ...).
    """
    if not papers:
        return 0
    now = time.time()
    new = 0
    with _connect() as conn:
        for i, p in enumerate(papers):
            pid = arxiv_pid(p.get('url', ''))
            if not pid:
                continue
            exists = conn.execute('SELECT 1 FROM papers WHERE pid = ?', (pid,)).fetchone()
            new += 0 if exists else 1
            conn.execute(
                """
                INSERT INTO papers (pid, version, title, authors, summary, url, pdf_url,
                                    categories, comment, journal_ref, doi, report_date,
                                    number, added_ts)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(pid) DO UPDATE SET
                    version = excluded.version,
                    title = excluded.title,
                    authors = excluded.authors,
                    summary = excluded.summary,
                    url = excluded.url,
                    pdf_url = excluded.pdf_url,
                    categories = excluded.categories,
                    comment = excluded.comment,
                    journal_ref = excluded.journal_ref,
                    doi = excluded.doi,
                    report_date = excluded.report_date,
                    number = excluded.number
                """,
                (
                    pid,
                    arxiv_version(p.get('url', '')),
                    (p.get('title') or '').replace('\n', ' ').strip(),
                    p.get('authors') or '',
                    p.get('summary') or '',
                    p.get('url') or '',
                    p.get('pdf_url') or '',
                    json.dumps(p.get('categories') or []),
                    p.get('comment') or '',
                    p.get('journal_ref') or '',
                    p.get('doi') or '',
                    report_date,
                    i + 1,
                    now,
                ),
            )
    return new


def all_papers() -> list[dict]:
    """Every stored paper, newest listing first, then by report number."""
    with _connect() as conn:
        rows = conn.execute('SELECT * FROM papers ORDER BY report_date DESC, number ASC').fetchall()
    return [_row_to_paper(r) for r in rows]


def get_paper(pid: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute('SELECT * FROM papers WHERE pid = ?', (pid,)).fetchone()
    return _row_to_paper(row) if row else None


def get_papers(pids: list[str]) -> dict[str, dict]:
    if not pids:
        return {}
    marks = ','.join('?' * len(pids))
    with _connect() as conn:
        rows = conn.execute(f'SELECT * FROM papers WHERE pid IN ({marks})', pids).fetchall()
    return {r['pid']: _row_to_paper(r) for r in rows}


def stats() -> dict:
    """Corpus fingerprint used to detect stale feature caches."""
    with _connect() as conn:
        row = conn.execute(
            'SELECT COUNT(*) AS n, COALESCE(MAX(added_ts), 0) AS latest, '
            'MIN(report_date) AS first_date, MAX(report_date) AS last_date FROM papers'
        ).fetchone()
    return dict(row)


def report_date_for_window_end(end_day: datetime.date) -> datetime.date:
    """Listing date that announces the submission window ending on ``end_day``.

    Windows end at 14:00 ET; the listing is dated the day after the 20:00 ET
    announcement. A Friday-ending window is announced Sunday and dated Monday.
    """
    return end_day + datetime.timedelta(days=3 if end_day.weekday() == 4 else 1)


def import_cache(cache_dir: str | None = None) -> int:
    """Backfill the corpus from the fetcher's per-window JSON cache files.

    Returns the number of newly added papers.
    """
    cache_dir = cache_dir or os.path.join(REPORTS_DIR, '.cache')
    added = 0
    for path in sorted(glob.glob(os.path.join(cache_dir, 'arxiv_*.json'))):
        m = _CACHE_NAME_RE.search(os.path.basename(path))
        if not m:
            continue
        end_day = datetime.datetime.strptime(m.group(2), '%Y%m%d').date()
        report_date = report_date_for_window_end(end_day).isoformat()
        try:
            with open(path, encoding='utf-8') as f:
                papers = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        n = upsert_papers(papers, report_date)
        added += n
        print(f'  {os.path.basename(path)} -> listing {report_date}: {len(papers)} papers, {n} new')
    return added
