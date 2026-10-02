"""Promote an abstract-only ("Other topics") report entry to a full LLM digest.

The LLM is asked for the entry of a single paper under the normal prompt
rules, with an override that forces a focus-topic classification. The entry
replaces the abstract-only block in the saved fragment, the field index is
updated, and the report, static site and wiki are rebuilt.
"""

from __future__ import annotations

import datetime
import os
import re

from core import corpus
from core.fetcher import ARXIV_TZ
from core.prompt import build_prompt
from core.providers import generate_text
from core.render import FRAGMENTS_DIR, save_html
from core.report_post import OTHER_LABEL, parse_index, render_index
from core.topics import FOCUS_LABELS

_OVERRIDE = """

IMPORTANT OVERRIDE FOR THIS RUN: the single paper below has been hand-selected for a full
entry. File it in the one or two most relevant **focus** categories (never only in index-only topics such as "{other}"), and
write its complete Part 3 entry. Output the index-box line(s) and the paper entry only; omit
Today's Highlights.
"""


def _paper_for(date: str, pid: str) -> tuple[list[dict], dict]:
    papers = sorted(
        (p for p in corpus.all_papers() if p['report_date'] == date), key=lambda p: p['number']
    )
    if not papers:
        raise ValueError(f'No papers in the corpus for listing {date}')
    match = [p for p in papers if p['pid'] == pid]
    if not match:
        raise ValueError(f'{pid} is not part of listing {date}')
    return papers, match[0]


def _as_fetched(p: dict) -> dict:
    """Corpus row -> the dict shape ``build_prompt`` / ``save_html`` expect."""
    return {
        'title': p['title'],
        'authors': p['authors'],
        'summary': p['summary'],
        'url': p['url'],
        'pdf_url': p.get('pdf_url', ''),
        'categories': p.get('categories', []),
        'comment': p.get('comment', ''),
        'journal_ref': p.get('journal_ref', ''),
        'doi': p.get('doi', ''),
    }


def digest_one(paper: dict, number: int) -> tuple[str, list[str], str]:
    """Return ``(entry_html, focus_labels, provider)`` for one paper numbered ``number``."""
    prompt = build_prompt([_as_fetched(paper)]) + _OVERRIDE.format(other=OTHER_LABEL)
    text, provider = generate_text(prompt)
    text = text.replace('```html', '').replace('```', '')
    m = re.search(r'<div class="paper-item"[^>]*id="p1">.*?</div>', text, re.S)
    if not m:
        raise RuntimeError('LLM output contained no paper entry')
    entry = m.group(0)
    entry = re.sub(r'id="p1"', f'id="p{number}"', entry, count=1)
    entry = re.sub(r'<h3>\[1\]', f'<h3>[{number}]', entry, count=1)
    labels = [label for label in parse_index(text) if label in FOCUS_LABELS]
    if not labels:
        raise RuntimeError('LLM did not file the paper in a focus category')
    return entry, labels, provider


def promote(date: str, pid: str, rebuild: bool = True) -> dict:
    papers, paper = _paper_for(date, pid)
    n = paper['number']
    frag_path = os.path.join(FRAGMENTS_DIR, f'{date}.html')
    if not os.path.exists(frag_path):
        raise FileNotFoundError(f'No report fragment for {date}; generate the report first')
    with open(frag_path, encoding='utf-8') as f:
        frag = f.read()

    entry, labels, provider = digest_one(paper, n)

    other_re = re.compile(rf'<div class="paper-item paper-other" id="p{n}">.*?</div>\n?', re.S)
    if other_re.search(frag):
        frag = other_re.sub(entry + '\n', frag, count=1)
    else:
        full_re = re.compile(rf'<div class="paper-item" id="p{n}">.*?</div>', re.S)
        if full_re.search(frag):
            frag = full_re.sub(entry, frag, count=1)
        else:  # append before the Other box if present, else at the end
            idx = frag.find('<div class="other-box">')
            frag = (
                (frag[:idx] + entry + '\n' + frag[idx:])
                if idx >= 0
                else frag.rstrip() + '\n' + entry
            )

    index = parse_index(frag)
    for label in list(index):
        index[label] = [x for x in index[label] if x != n]
    for label in labels:
        index.setdefault(label, []).append(n)
    index = {k: v for k, v in index.items() if v}
    m = re.search(r'<div class="index-box">.*?</div>', frag, re.S)
    frag = frag[: m.start()] + render_index(index) + frag[m.end() :]

    as_of = ARXIV_TZ.localize(datetime.datetime.strptime(date, '%Y-%m-%d').replace(hour=12))
    save_html([_as_fetched(p) for p in papers], frag, provider, as_of=as_of)

    if rebuild:
        import build_site
        from core import wiki

        build_site.build()
        wiki.Build().run()
        wiki.export_html()
    return {'date': date, 'pid': pid, 'number': n, 'topics': labels, 'provider': provider}


def has_full_entry(date: str, pid: str) -> bool:
    """True when the saved fragment holds a full (non abstract-only) entry for ``pid``."""
    frag_path = os.path.join(FRAGMENTS_DIR, f'{date}.html')
    if not os.path.exists(frag_path):
        return False
    with open(frag_path, encoding='utf-8') as f:
        frag = f.read()
    _papers, paper = _paper_for(date, pid)
    return re.search(rf'<div class="paper-item" id="p{paper["number"]}">', frag) is not None


def rerender(date: str, provider: str = 'claude') -> str:
    """Re-render one day's report from its stored fragment (applies the current feedback)."""
    papers = sorted(
        (p for p in corpus.all_papers() if p['report_date'] == date), key=lambda p: p['number']
    )
    with open(os.path.join(FRAGMENTS_DIR, f'{date}.html'), encoding='utf-8') as f:
        frag = f.read()
    as_of = ARXIV_TZ.localize(datetime.datetime.strptime(date, '%Y-%m-%d').replace(hour=12))
    return save_html([_as_fetched(p) for p in papers], frag, provider, as_of=as_of)
