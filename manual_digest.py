"""Write a day's digest by hand (or in a chat) instead of calling an LLM provider.

    python manual_digest.py prompt 2026-09-01            # print the exact prompt the LLM would get
    python manual_digest.py prompt 2026-09-01 --out d/   # also write d/prompt_<date>.txt + d/papers_<date>.json
    python manual_digest.py save   2026-09-01 frag.html  # validate the HTML body, render the report,
                                                         # update the corpus (site/wiki are NOT rebuilt)

The fragment must follow the prompt rules: starts with ``<div class="index-box">``, one
``<div class="paper-item" id="pN">`` per focus-topic paper, arXiv links and status badges
copied verbatim, no LaTeX. ``save`` refuses anything that does not validate.
"""

from __future__ import annotations

import argparse
import datetime
from html.parser import HTMLParser
import json
import os
import re
import sys
from typing import ClassVar

from core import corpus
from core.fetcher import ARXIV_TZ, fetch_arxiv_papers
from core.prompt import _render_status_badge, build_prompt
from core.render import save_html
from core.report_post import digested_numbers, parse_index
from core.topics import FOCUS_LABELS, OTHER_LABEL, TOPIC_NAME

_H3_RE = r'<div class="paper-item" id="p{n}">\s*<h3>\[{n}\] <a href="([^"]+)">([^<]+)</a>(.*?)</h3>'


def _as_of(date: str) -> datetime.datetime:
    return ARXIV_TZ.localize(datetime.datetime.strptime(date, '%Y-%m-%d').replace(hour=12))


def _papers(date: str) -> list[dict]:
    papers = fetch_arxiv_papers(as_of=_as_of(date))
    if not papers:
        raise SystemExit(f'No papers for listing {date} (weekend/holiday or fetch problem).')
    return papers


class _Balance(HTMLParser):
    TAGS: ClassVar[set[str]] = {
        'div',
        'p',
        'h3',
        'span',
        'sup',
        'sub',
        'a',
        'strong',
        'details',
        'summary',
    }

    def __init__(self):
        super().__init__()
        self.depth = 0
        self.min_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.TAGS:
            self.depth += 1

    def handle_endtag(self, tag):
        if tag in self.TAGS:
            self.depth -= 1
            self.min_depth = min(self.min_depth, self.depth)


def validate(fragment: str, papers: list[dict]) -> list[str]:
    """Return a list of problems (empty when the fragment is acceptable)."""
    errors: list[str] = []
    frag = fragment.strip()
    if not frag.startswith('<'):
        errors.append('first character must be "<"')
    if not frag.endswith('</div>'):
        errors.append('must end with </div>')
    if '$' in frag:
        errors.append('LaTeX "$" found; use Unicode / <sub> / <sup>')
    if '```' in frag:
        errors.append('code fences found')
    bal = _Balance()
    bal.feed(frag)
    if bal.depth != 0 or bal.min_depth < 0:
        errors.append(f'unbalanced tags (final depth {bal.depth})')
    if '<div class="index-box">' not in frag:
        errors.append('missing <div class="index-box">')

    index = parse_index(frag)
    n = len(papers)
    filed: dict[int, list[str]] = {}
    for label, nums in index.items():
        if label not in TOPIC_NAME:
            errors.append(f'unknown index label: {label!r}')
        for k in nums:
            filed.setdefault(k, []).append(label)
    for k in range(1, n + 1):
        if k not in filed:
            errors.append(f'paper [{k}] missing from the field index')
    for k, labels in filed.items():
        if k < 1 or k > n:
            errors.append(f'index refers to non-existent paper [{k}]')
        if OTHER_LABEL in labels and len(labels) > 1:
            errors.append(f'paper [{k}] is in "{OTHER_LABEL}" and in another topic')
        if len(labels) > 2:
            errors.append(f'paper [{k}] in more than two topics')

    have = digested_numbers(frag)
    for k in range(1, n + 1):
        in_focus = any(x in FOCUS_LABELS for x in filed.get(k, []))
        if in_focus and k not in have:
            errors.append(f'paper [{k}] is in a focus topic but has no entry')
        if not in_focus and k in have:
            errors.append(f'paper [{k}] has an entry but is filed only under index-only topics')
    for k in sorted(have):
        p = papers[k - 1] if 0 < k <= n else None
        m = re.search(_H3_RE.format(n=k), frag, re.S)
        if not m or p is None:
            errors.append(f'entry [{k}]: malformed <h3>')
            continue
        if m.group(1) != p['url']:
            errors.append(f'entry [{k}]: URL must be {p["url"]}')
        badge = _render_status_badge(p)
        if m.group(3).strip() != badge:
            errors.append(f'entry [{k}]: status badge must be exactly {badge!r}')
        body = re.search(rf'<div class="paper-item" id="p{k}">(.*?)</div>', frag, re.S).group(1)
        for label in ('Title:', 'Authors:', 'Methods:', 'Results:'):
            if f'<strong>{label}</strong>' not in body:
                errors.append(f'entry [{k}]: missing <strong>{label}</strong>')
        if 'class="method-tag">[' not in body:
            errors.append(
                f'entry [{k}]: method tag must look like <span class="method-tag">[Observation]</span>'
            )
    return errors


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('prompt', help='print / write the exact LLM prompt for a listing date')
    s.add_argument('date')
    s.add_argument('--out', help='directory to write prompt_<date>.txt and papers_<date>.json')
    s = sub.add_parser('save', help='validate a hand-written fragment and render the report')
    s.add_argument('date')
    s.add_argument('fragment', help='path to the HTML body fragment')
    s.add_argument(
        '--provider', default='claude-session', help='provider label shown in the header'
    )
    s.add_argument('--force', action='store_true', help='save despite validation errors')
    a = ap.parse_args()

    papers = _papers(a.date)
    if a.cmd == 'prompt':
        prompt = build_prompt(papers)
        if a.out:
            os.makedirs(a.out, exist_ok=True)
            with open(os.path.join(a.out, f'prompt_{a.date}.txt'), 'w', encoding='utf-8') as f:
                f.write(prompt)
            with open(os.path.join(a.out, f'papers_{a.date}.json'), 'w', encoding='utf-8') as f:
                json.dump(papers, f, ensure_ascii=False, indent=1, default=str)
            print(f'{a.date}: {len(papers)} papers -> {a.out}/prompt_{a.date}.txt')
        else:
            sys.stdout.write(prompt)
        return 0

    with open(a.fragment, encoding='utf-8') as f:
        frag = f.read().strip()
    errors = validate(frag, papers)
    if errors:
        print(f'❌ {len(errors)} problem(s) in {a.fragment}:')
        for e in errors[:40]:
            print('   -', e)
        if not a.force:
            return 1
    save_html(papers, frag, a.provider, as_of=_as_of(a.date))
    added = corpus.upsert_papers(papers, a.date)
    print(
        f'✅ {a.date}: {len(papers)} papers, {len(digested_numbers(frag))} full entries; corpus +{added}'
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
