"""Per-paper feedback (👍 / 👎) stored next to the corpus.

* ``like``    -- the paper matters: an abstract-only entry is promoted to a full digest,
                 a full entry gets a "liked" badge, and likes act as positives for the recommender.
* ``dislike`` -- the paper is dismissed: its entry moves to the collapsed "Dismissed papers"
                 section and it no longer counts as a focus paper (★ counts, highlights, summaries).
"""

from __future__ import annotations

import sqlite3
import time

from core import corpus

VERDICTS = ('like', 'dislike')
_SCHEMA = """
CREATE TABLE IF NOT EXISTS feedback (
    pid     TEXT PRIMARY KEY,
    verdict TEXT NOT NULL,
    ts      REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS notes (
    pid  TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    ts   REAL NOT NULL
);
"""


def _connect() -> sqlite3.Connection:
    conn = corpus._connect()
    conn.executescript(_SCHEMA)
    return conn


def set_verdict(pid: str, verdict: str | None) -> None:
    """Store ``like`` / ``dislike`` for ``pid``; ``None`` removes it."""
    with _connect() as conn:
        if verdict in VERDICTS:
            conn.execute(
                'INSERT INTO feedback (pid, verdict, ts) VALUES (?, ?, ?) '
                'ON CONFLICT(pid) DO UPDATE SET verdict = excluded.verdict, ts = excluded.ts',
                (pid, verdict, time.time()),
            )
        else:
            conn.execute('DELETE FROM feedback WHERE pid = ?', (pid,))


def all_verdicts() -> dict[str, str]:
    with _connect() as conn:
        return {r[0]: r[1] for r in conn.execute('SELECT pid, verdict FROM feedback')}


def liked() -> list[str]:
    return [p for p, v in all_verdicts().items() if v == 'like']


def dismissed() -> set[str]:
    return {p for p, v in all_verdicts().items() if v == 'dislike'}


def set_note(pid: str, text: str) -> None:
    """Store a personal note for ``pid``; an empty text deletes it."""
    text = (text or '').strip()
    with _connect() as conn:
        if text:
            conn.execute(
                'INSERT INTO notes (pid, text, ts) VALUES (?, ?, ?) '
                'ON CONFLICT(pid) DO UPDATE SET text = excluded.text, ts = excluded.ts',
                (pid, text, time.time()),
            )
        else:
            conn.execute('DELETE FROM notes WHERE pid = ?', (pid,))


def all_notes() -> dict[str, str]:
    with _connect() as conn:
        return {r[0]: r[1] for r in conn.execute('SELECT pid, text FROM notes')}
