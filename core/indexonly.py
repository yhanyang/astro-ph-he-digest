"""Index-only reports: every paper filed by keyword, no LLM digest.

Used to cover a date range quickly and for free (phase 1 of a backfill). The
report lists all papers with title, authors and abstract under the keyword
classification; a later real run (``report.py`` / ``backfill.sh``) overwrites
it. Fragments carry :data:`INDEX_ONLY_MARK` so tools can tell them apart.
"""

from __future__ import annotations

import re

from core.report_post import render_index
from core.topics import (
    _EFXT_EXCLUDE_RE_SAFE,
    FOCUS_LABELS,
    GRB_LABEL,
    OTHER_LABEL,
    PRIMARY_LABEL,
    index_topic_for,
)

INDEX_ONLY_MARK = '<!-- index-only -->'
PROVIDER = 'index-only (keywords)'

# Ordered keyword rules for the focus tier; a paper may get up to two labels.
_FOCUS_RULES: list[tuple[re.Pattern, str]] = [
    (
        re.compile(
            r'gamma[- ]ray bursts?|\bGRBs?\b|\bGRB ?\d{6}[A-Z]?\b|afterglow|collapsar', re.I
        ),
        GRB_LABEL,
    ),
    (
        re.compile(r'fast[- ]x-?ray transients?|\bE?FXTs?\b|\bEP\d{6}[a-z]?\b', re.I),
        'Extragalactic Fast X-ray Transients (EFXT / FXT)',
    ),
    (
        re.compile(
            r'fast radio bursts?|\bFRBs?\b|\bFRB ?20\d{6}[A-Z]?\b|persistent radio source', re.I
        ),
        'Fast Radio Bursts (FRB)',
    ),
    (
        re.compile(r'kilonova|macronova|\br-process|lanthanide|AT ?2017gfo', re.I),
        'Kilonovae & r-process (Kilonova)',
    ),
    (re.compile(r'tidal[- ]disruption|\bTDEs?\b', re.I), 'Tidal Disruption Events (TDE)'),
    (re.compile(r'quasi[- ]periodic eruptions?|\bQPEs?\b', re.I), 'Quasi-Periodic Eruptions (QPE)'),
    (
        re.compile(r'magnetar|soft gamma[- ]repeater|\bSGRs?\b|\bAXPs?\b|giant flare', re.I),
        'Magnetars (Magnetar / SGR / AXP)',
    ),
    (
        re.compile(
            r'gravitational[- ]waves?|\bGWs?\b|\bGW\d{6}|\bLIGO|\bVirgo\b|KAGRA|\bLISA\b|pulsar timing array|\bPTA\b|'
            r'binary black holes?|\bBBHs?\b|binary neutron stars?|\bBNSs?\b|neutron[- ]star mergers?|compact binar|'
            r'\bEMRIs?\b|\bGWTC|stochastic (?:gravitational[- ]wave )?background|\bSGWB\b|ringdown|inspiral',
            re.I,
        ),
        PRIMARY_LABEL,
    ),
]


def classify(paper: dict) -> list[str]:
    """One or two labels for a paper from title + abstract keywords."""
    text = f'{paper.get("title", "")} {paper.get("summary", "")}'
    labels: list[str] = []
    for regex, label in _FOCUS_RULES:
        if regex.search(text):
            if label.startswith('Extragalactic Fast') and _EFXT_EXCLUDE_RE_SAFE.search(text):
                continue
            labels.append(label)
        if len(labels) == 2:
            break
    if len(labels) < 2:
        extra = index_topic_for(text)
        if extra != OTHER_LABEL or not labels:
            labels.append(extra)
    return labels[:2]


def build_fragment(papers: list[dict]) -> str:
    """Field index only (plus the marker); ``save_html`` adds the abstract entries."""
    index: dict[str, list[int]] = {}
    for n, p in enumerate(papers, start=1):
        for label in classify(p):
            index.setdefault(label, []).append(n)
    return render_index(index) + '\n' + INDEX_ONLY_MARK


def is_index_only(fragment: str) -> bool:
    return INDEX_ONLY_MARK in fragment


def focus_count(papers: list[dict]) -> int:
    return sum(1 for p in papers if any(label in FOCUS_LABELS for label in classify(p)))
