"""Obsidian-compatible wiki built from the daily reports and the paper corpus.

Design follows AgriciDaniel/claude-obsidian: the vault is a plain directory
of Markdown (``wiki/``), sources are preserved as content-addressed copies
before synthesis (``wiki/.raw/``), every build is journaled
(``wiki/.log/operations.jsonl``), and a linter reports dead links, orphans,
metadata gaps, stale indexes and overdue reviews.

Long-term maintenance rule: every note has one machine-owned block between
``<!-- auto:start -->`` and ``<!-- auto:end -->``. ``build`` rewrites only
that block (and the machine-owned frontmatter keys); anything a human writes
outside it survives every rebuild. A changed auto block is reported, never
silently overwritten without a journal entry.

Note types (frontmatter ``type``):

* ``paper``   -- one note per arXiv paper (``papers/<arxiv id>.md``)
* ``topic``   -- Map of Content per field-index category (``topics/``)
* ``object``  -- Map of Content per named astrophysical source (``objects/``)
* ``daily``   -- one note per listing day (``daily/<date>.md``)
* ``weekly``  -- extractive rollup of a week (``weekly/<ISO week>.md``)
* ``home``    -- vault entry point (``Home.md``)
"""

from __future__ import annotations

import datetime
import hashlib
import html as _html
import json
import os
import re
import uuid

from core import corpus
from core.render import FRAGMENTS_DIR

WIKI_DIR = os.getenv('WIKI_DIR') or (
    './reports/.wiki' if os.path.isdir('./reports/.wiki') else './wiki'
)
RAW_DIR = os.path.join(WIKI_DIR, '.raw')
LOG_DIR = os.path.join(WIKI_DIR, '.log')
LOG_PATH = os.path.join(LOG_DIR, 'operations.jsonl')
REVIEW_DAYS = int(os.getenv('WIKI_REVIEW_DAYS', '90'))

AUTO_START = '<!-- auto:start -->'
AUTO_END = '<!-- auto:end -->'

from core.topics import (  # noqa: E402  (shared taxonomy)
    FOCUS_LABELS,
    OTHER_GROUP,
    TOPIC_NAME,
    TOPICS,
)

UNCLASSIFIED = 'Unclassified'

# Named-source patterns (deterministic, no LLM). Each yields a canonical name.
_OBJECT_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'\bGRB\s?(\d{6}[A-Z]?)\b'), 'GRB {0}'),
    (re.compile(r'\bGW\s?(\d{6}(?:_\d{6})?)\b'), 'GW{0}'),
    (re.compile(r'\bFRB\s?(\d{8}[A-Z]?|\d{6}[A-Z]?)\b'), 'FRB {0}'),
    (re.compile(r'\bSN\s?((?:19|20)\d{2}[a-zA-Z]{1,4})\b'), 'SN {0}'),
    (re.compile(r'\bAT\s?(20\d{2}[a-z]{2,5})\b'), 'AT {0}'),
    (re.compile(r'\bZTF(\d{2}[a-z]{7})\b'), 'ZTF{0}'),
    (re.compile(r'\bEP(\d{6}[a-z]?)\b'), 'EP{0}'),
    (re.compile(r'\bPSR\s?([BJ]\d{4}[+\-−]\d{2,4}[A-Za-z]?)\b'), 'PSR {0}'),
    (re.compile(r'\bSGR\s?([BJ]?\d{4}[+\-−]\d{2,4})\b'), 'SGR {0}'),
    (
        re.compile(
            r'\b(HESS|LHAASO|HAWC|4FGL|3FHL|4FGL-DR\d|MAXI|XTE|IGR|GRO|1RXS|3HWC)\s?(J\d{4}(?:\.\d)?[+\-−]\d{2,4}[a-z]?)\b'
        ),
        '{0} {1}',
    ),
    (re.compile(r'\bSwift\s?(J\d{4}\.\d[+\-−]\d{4,6})\b'), 'Swift {0}'),
    (re.compile(r'\b1E\s?(\d{4}\.\d[+\-−]\d{4})\b'), '1E {0}'),
    (
        re.compile(
            r'\b(1ES|PKS|TXS|PG|B2|BZB|RX|OJ|S5|QSO|RBS)\s?(J?\d{4}(?:\.\d)?[+\-−]\d{2,4})\b'
        ),
        '{0} {1}',
    ),
    (re.compile(r'\bMrk\s?(\d{2,4})\b'), 'Mrk {0}'),
    (re.compile(r'\bNGC\s?(\d{2,4})\b'), 'NGC {0}'),
    (re.compile(r'\b3C\s?(\d{2,3}(?:\.\d)?)\b'), '3C {0}'),
    (re.compile(r'\bM\s?(31|33|42|51|81|82|87|101)\b(?!\s*(?:dwarf|star|class))'), 'M{0}'),
    (re.compile(r'\bIceCube[- ](\d{6}[A-Z]?)\b'), 'IceCube-{0}'),
    (re.compile(r'\b(Cyg|Cygnus)\s?X-([13])\b'), 'Cyg X-{1}'),
    (re.compile(r'\b(Sco|Her|Cen|Aql)\s?X-1\b'), '{0} X-1'),
    (re.compile(r'\bGX\s?(\d{1,3}[+\-−]\d{1,2}|\d{3})\b'), 'GX {0}'),
    (re.compile(r'\bSgr\s?A\*'), 'Sgr A star'),
    (re.compile(r'\bM87\*'), 'M87 star'),
    (re.compile(r'\b(Cas A|Cassiopeia A)\b'), 'Cas A'),
    (
        re.compile(
            r'\b(SS\s?433|HLX-1|Geminga|Vela pulsar|Crab pulsar|Crab Nebula|Crab nebula|Cen A|Centaurus A|Tycho|Kepler\'s SNR|RX J1713\.7-3946|Terzan 5|47 Tuc|LMC|SMC|Boomerang|TeV J2032\+4130)\b'
        ),
        '{0}',
    ),
]
_OBJECT_CANON = {
    'Centaurus A': 'Cen A',
    'Cassiopeia A': 'Cas A',
    'Cygnus': 'Cyg',
    'Crab nebula': 'Crab Nebula',
    'SS433': 'SS 433',
}

# Fragment parsing (the LLM output template is fixed by core/prompt.py).
_PAPER_RE = re.compile(r'<div class="paper-item( paper-other)?" id="p(\d+)">(.*?)</div>', re.S)
_INDEX_BOX_RE = re.compile(r'<div class="index-box">(.*?)</div>', re.S)
_HIGHLIGHT_BOX_RE = re.compile(r'<div class="highlight-box">(.*?)</div>', re.S)
_INDEX_LINE_RE = re.compile(r'<p>\s*<strong>(.*?):?\s*</strong>(.*?)</p>', re.S)
_HIGHLIGHT_LINE_RE = re.compile(r'<p>\s*<a href="#p(\d+)">\[\d+\]</a>\s*(.*?)</p>', re.S)
_ANCHOR_NUM_RE = re.compile(r'href="#p(\d+)"')
_H3_RE = re.compile(r'<h3>.*?<a href="([^"]+)">([^<]+)</a>(.*?)</h3>', re.S)
_STATUS_RE = re.compile(r'<span class="status-tag status-(\w+)">(.*?)</span>', re.S)
_FIELD_RE = re.compile(r'<p>\s*<strong>([^<]+?):\s*</strong>(.*?)</p>', re.S)
_METHOD_RE = re.compile(r'<span class="method-tag">\[(.*?)\]</span>\s*', re.S)
_A_RE = re.compile(r'<a href="([^"]+)"[^>]*>(.*?)</a>', re.S)
_TAG_RE = re.compile(r'</?(?:strong|em|b|i|p|br)\s*/?>', re.S)
_WIKILINK_RE = re.compile(r'\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]')
_FM_RE = re.compile(r'\A---\n(.*?)\n---\n', re.S)


# --------------------------------------------------------------------------- helpers
def _today() -> str:
    return datetime.date.today().isoformat()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_name(name: str) -> str:
    """File-name safe note title (Obsidian forbids * " \\ / < > : | ? # ^ [ ])."""
    name = name.replace('*', ' star').replace('/', '-').replace(':', ' -')
    return re.sub(r'[\"\\<>|?#^\[\]]', '', name).strip()


def clean_title(t: str) -> str:
    """Strip arXiv title LaTeX ($z=5$, {\\it Fermi}, \\textit{}) for link aliases and headings."""
    t = re.sub(r'\\(?:textit|textbf|emph|mathrm|rm|it)\s*\{([^}]*)\}', r'\1', t)
    t = re.sub(r'\{\\(?:it|bf|rm)\s+([^}]*)\}', r'\1', t)
    t = t.replace('$', '').replace('\\,', ' ').replace('~', ' ')
    return re.sub(r'\s+', ' ', t).strip()


def _literal(text: str) -> str:
    """Escape square brackets so abstracts like ``[Wolf-Rayet]([WR])`` stay plain text in Markdown."""
    return text.replace('[', '\\[').replace(']', '\\]')


def _html_to_md(fragment: str) -> str:
    """Inline HTML from the digest -> Markdown; keeps <sub>/<sup>/errbar (Obsidian renders them)."""
    s = _METHOD_RE.sub('', fragment)
    # Square brackets in digest text are literal ([22], [WR], ...), never Markdown links or wikilinks.
    s = s.replace('[', '\\[').replace(']', '\\]')
    s = _A_RE.sub(lambda m: f'[{m.group(2)}]({m.group(1)})', s)
    s = _TAG_RE.sub('', s)
    s = _html.unescape(s)
    return re.sub(r'\s+', ' ', s).strip()


def _yaml_scalar(v) -> str:
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    if s == '' or re.search(r'[:#\[\]{}&*!|>\'"%@`,]|^\s|\s$|^(true|false|null|yes|no)$', s, re.I):
        return json.dumps(s, ensure_ascii=False)
    return s


_OPTIONAL_AUTO_KEYS = ('citations', 'scix_bibcode', 'ads_bibcode')


def _dump_frontmatter(fm: dict) -> str:
    lines = ['---']
    for k, v in fm.items():
        if isinstance(v, list):
            if not v:
                lines.append(f'{k}: []')
            else:
                lines.append(f'{k}:')
                lines.extend(f'  - {_yaml_scalar(x)}' for x in v)
        else:
            lines.append(f'{k}: {_yaml_scalar(v)}')
    lines.append('---')
    return '\n'.join(lines) + '\n'


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Tiny YAML subset parser (scalars + block lists) sufficient for our own notes."""
    m = _FM_RE.match(text)
    if not m:
        return {}, text
    fm: dict = {}
    key = None
    for line in m.group(1).split('\n'):
        if line.startswith('  - ') and key is not None:
            fm.setdefault(key, [])
            if not isinstance(fm[key], list):
                fm[key] = []
            fm[key].append(_unquote(line[4:].strip()))
        elif ':' in line and not line.startswith(' '):
            key, _, val = line.partition(':')
            key = key.strip()
            val = val.strip()
            fm[key] = [] if val == '[]' else (_unquote(val) if val else None)
            if fm[key] is None:
                fm[key] = []  # block list follows
    return fm, text[m.end() :]


def _unquote(s: str):
    if s.startswith('"') and s.endswith('"'):
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            return s[1:-1]
    if s in ('true', 'false'):
        return s == 'true'
    if re.fullmatch(r'-?\d+', s):
        return int(s)
    return s


_DESIGNATION_DATE_RES: list[tuple[re.Pattern, str]] = [
    (re.compile(r'^(?:GRB|GW|EP|IceCube-)\s?(\d{6})'), 'yymmdd'),
    (re.compile(r'^FRB\s?(\d{8})'), 'yyyymmdd'),
    (re.compile(r'^FRB\s?(\d{6})'), 'yymmdd'),
    (re.compile(r'^(?:SN|AT)\s?((?:19|20)\d{2})[a-zA-Z]'), 'yyyy'),
    (re.compile(r'^ZTF(\d{2})[a-z]'), 'yy'),
]


def object_discovery_date(name: str) -> datetime.date | None:
    """Discovery date encoded in a transient designation (GRB 250419A -> 2025-04-19).

    Year-only designations (SN 2025abc, ZTF25...) resolve to 1 January of that year.
    Returns ``None`` for catalogue names without a date (PSR, NGC, ...).
    """
    for pat, kind in _DESIGNATION_DATE_RES:
        m = pat.match(name)
        if not m:
            continue
        d = m.group(1)
        try:
            if kind == 'yymmdd':
                yy = int(d[:2])
                century = 2000 if yy <= datetime.date.today().year % 100 + 1 else 1900
                return datetime.date(century + yy, int(d[2:4]), int(d[4:6]))
            if kind == 'yyyymmdd':
                return datetime.date(int(d[:4]), int(d[4:6]), int(d[6:8]))
            if kind == 'yyyy':
                return datetime.date(int(d), 1, 1)
            if kind == 'yy':
                return datetime.date(2000 + int(d), 1, 1)
        except ValueError:
            return None
    return None


def extract_objects(text: str) -> list[str]:
    """Canonical names of astrophysical sources mentioned in ``text``."""
    found: set[str] = set()
    for pat, fmt in _OBJECT_PATTERNS:
        for m in pat.finditer(text):
            groups = [_OBJECT_CANON.get(g, g) for g in m.groups() if g is not None]
            name = fmt.format(*groups) if groups else fmt
            name = name.replace('−', '-')
            found.add(_OBJECT_CANON.get(name, name))
    return sorted(found)


# --------------------------------------------------------------------------- fragment parsing
def parse_fragment(html_text: str) -> dict:
    """Pull index, highlights and per-paper digest fields out of a report fragment."""
    topics_by_num: dict[int, list[str]] = {}
    m = _INDEX_BOX_RE.search(html_text)
    if m:
        for label, body in _INDEX_LINE_RE.findall(m.group(1)):
            label = _html.unescape(label).strip().rstrip(':')
            for n in _ANCHOR_NUM_RE.findall(body):
                topics_by_num.setdefault(int(n), []).append(label)

    highlights: dict[int, str] = {}
    m = _HIGHLIGHT_BOX_RE.search(html_text)
    if m:
        for n, text in _HIGHLIGHT_LINE_RE.findall(m.group(1)):
            highlights[int(n)] = _html_to_md(text)

    papers: dict[int, dict] = {}
    for other, n, body in _PAPER_RE.findall(html_text):
        n = int(n)
        entry: dict = {
            'number': n,
            'fields': {},
            'method': '',
            'status': '',
            'status_class': '',
            'other': bool(other),
        }
        h = _H3_RE.search(body)
        if h:
            entry['url'] = h.group(1)
            entry['arxiv_id'] = h.group(2).strip()
            st = _STATUS_RE.search(h.group(3))
            if st:
                entry['status_class'] = st.group(1)
                entry['status'] = _html.unescape(re.sub(r'\s+', ' ', st.group(2))).strip()
        for label, val in _FIELD_RE.findall(body):
            label = _html.unescape(label).strip()
            if label == 'Methods':
                mm = _METHOD_RE.search(val)
                entry['method'] = mm.group(1) if mm else ''
            entry['fields'][label] = _html_to_md(val)
        papers[n] = entry
    return {'topics': topics_by_num, 'highlights': highlights, 'papers': papers}


def load_digests() -> dict[str, dict]:
    """``{listing_date: parsed fragment}`` for every saved fragment."""
    out = {}
    if not os.path.isdir(FRAGMENTS_DIR):
        return out
    for fn in sorted(os.listdir(FRAGMENTS_DIR)):
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}\.html', fn):
            with open(os.path.join(FRAGMENTS_DIR, fn), encoding='utf-8') as f:
                out[fn[:-5]] = parse_fragment(f.read())
    return out


# --------------------------------------------------------------------------- note writing
class Build:
    """One idempotent synchronisation of the vault with corpus + digests."""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.op_id = uuid.uuid4().hex[:12]
        self.created: list[str] = []
        self.updated: list[str] = []
        self.unchanged = 0
        self.today = _today()

    # -- file primitives ---------------------------------------------------
    def _write_note(
        self, rel: str, auto_fm: dict, auto_body: str, human_default: str, human_first: bool = False
    ) -> None:
        """Merge the machine-owned parts into ``rel`` while preserving human text.

        * Frontmatter: keys in ``auto_fm`` are replaced; other keys are kept.
          ``created`` is kept from the existing note.
        * Body: text between AUTO_START/AUTO_END is replaced; everything else is kept.
          A note without markers (hand-made) gets the auto block appended.
        """
        path = os.path.join(WIKI_DIR, rel)
        existing = None
        if os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                existing = f.read()

        if existing is None:
            fm = dict(auto_fm)
            fm['created'] = self.today
            fm['updated'] = self.today
            auto = f'{AUTO_START}\n{auto_body.rstrip()}\n{AUTO_END}\n'
            human = f'{human_default.rstrip()}\n' if human_default.strip() else ''
            body = (
                f'{human}\n{auto}'
                if (human_first and human)
                else f'{auto}\n{human}'
                if human
                else auto
            )
            new_text = _dump_frontmatter(fm) + body
        else:
            old_fm, old_body = _parse_frontmatter(existing)
            fm = dict(old_fm)
            # machine-owned keys that are only present when there is data (e.g. SciX citations)
            for key in _OPTIONAL_AUTO_KEYS:
                if key not in auto_fm:
                    fm.pop(key, None)
            fm.update(auto_fm)
            fm['created'] = old_fm.get('created') or self.today
            if AUTO_START in old_body and AUTO_END in old_body:
                pre, rest = old_body.split(AUTO_START, 1)
                _, post = rest.rsplit(AUTO_END, 1)
                body = f'{pre}{AUTO_START}\n{auto_body.rstrip()}\n{AUTO_END}{post}'
            else:
                body = f'{old_body.rstrip()}\n\n{AUTO_START}\n{auto_body.rstrip()}\n{AUTO_END}\n'
            # Only bump `updated` when the machine-owned content actually changed.
            probe_fm = dict(fm)
            probe_fm['updated'] = old_fm.get('updated', self.today)
            if _dump_frontmatter(probe_fm) + body == existing:
                self.unchanged += 1
                return
            fm['updated'] = self.today
            new_text = _dump_frontmatter(fm) + body

        (self.created if existing is None else self.updated).append(rel)
        if self.dry_run:
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(new_text)

    def _write_raw(self, date: str, papers: list[dict]) -> str:
        """Content-addressed copy of the day's source records; returns relative path."""
        data = json.dumps(papers, ensure_ascii=False, indent=1, sort_keys=True).encode('utf-8')
        digest = _sha256(data)
        rel = f'.raw/{date}.{digest[:12]}.json'
        path = os.path.join(WIKI_DIR, rel)
        if not self.dry_run and not os.path.exists(path):
            os.makedirs(RAW_DIR, exist_ok=True)
            with open(path, 'wb') as f:
                f.write(data)
        return rel

    # -- note builders -----------------------------------------------------
    @staticmethod
    def _paper_link(p: dict) -> str:
        return f'[[{p["pid"]}|{clean_title(p["title"])}]]'

    @staticmethod
    def _short_authors(authors: str, n: int = 3) -> str:
        parts = [a.strip() for a in authors.split(',') if a.strip()]
        return ', '.join(parts[:n]) + (' et al.' if len(parts) > n else '')

    def paper_note(
        self,
        p: dict,
        digest: dict | None,
        topics: list[str],
        highlight: str | None,
        objects: list[str],
        raw_rel: str,
        entry_kind: str = 'full',
    ) -> None:
        fields = digest['fields'] if digest else {}
        method = digest['method'] if digest else ''
        status = digest['status'] if digest else ''
        fm = {
            'type': 'paper',
            'arxiv': p['pid'],
            'version': p.get('version') or '',
            'title': p['title'],
            'authors': [a.strip() for a in p['authors'].split(',') if a.strip()],
            'listing': p['report_date'],
            'report_number': p['number'],
            'categories': p.get('categories') or [],
            'topics': [TOPIC_NAME.get(t, t) for t in topics] or [UNCLASSIFIED],
            'method': method,
            'status': status or 'preprint',
            'journal_ref': p.get('journal_ref') or '',
            'doi': p.get('doi') or '',
            'objects': objects,
            'highlight': bool(highlight),
            'verdict': p.get('_verdict', ''),
            'digest': bool(digest),
            'entry': 'full' if digest else entry_kind,
            'url': p['url'],
            'source': raw_rel,
            'source_sha256': _sha256(json.dumps(p, ensure_ascii=False, sort_keys=True).encode()),
        }
        if p.get('_cites'):  # only when SciX knows the paper (needs a SciX token to fill)
            fm['citations'] = int(p['_cites'].get('n') or 0)
            fm['scix_bibcode'] = p['_cites'].get('bibcode', '')
        head = [f'# {clean_title(p["title"])}', '']
        meta = [
            f'**[arXiv:{p["pid"]}{p.get("version") or ""}]({p["url"]})**',
            f'[[{p["report_date"]}]] · [{p["number"]}]',
        ]
        if method:
            meta.append(f'`{method}`')
        if status:
            meta.append(status)
        if p.get('_cites') and p['_cites'].get('n'):
            from core.citations import scix_url

            meta.append(
                f'**{p["_cites"]["n"]} citation{"s" if p["_cites"]["n"] != 1 else ""}** '
                f'([SciX]({scix_url(p["_cites"]["bibcode"])}), {p["_cites"]["fetched"]})'
            )
        head.append(' · '.join(meta))
        head.append('')
        head.append(f'**Authors:** {p["authors"]}')
        head.append('')
        head.append(
            '**Topics:** ' + ', '.join(f'[[{TOPIC_NAME.get(t, t)}]]' for t in topics)
            if topics
            else f'**Topics:** [[{UNCLASSIFIED}]]'
        )
        if objects:
            head.append('')
            head.append('**Objects:** ' + ', '.join(f'[[{_safe_name(o)}]]' for o in objects))
        if highlight:
            head.append('')
            head.append(f'> [!tip] Highlight of {p["report_date"]}\n> {highlight}')
        if p.get('_note'):
            head.append('')
            head.append('> [!quote] Personal note\n> ' + _literal(p['_note']).replace('\n', '\n> '))
        body = head[:]
        for label in ('Research question', 'Methods', 'Results', 'Limitations & next steps'):
            if fields.get(label):
                body += ['', f'## {label}', '', fields[label]]
        if not digest:
            if entry_kind == 'abstract':
                body += [
                    '',
                    '> [!note] Abstract only — no digest for this paper yet. '
                    f'Promote it with `python promote.py {p["report_date"]} {p["pid"]}` or the ▲ button in the web UI.',
                ]
            else:
                body += [
                    '',
                    '> [!warning] No report entry for this paper yet. '
                    f'Regenerate the report for {p["report_date"]} (`./run_report.sh --date {p["report_date"]}`).',
                ]
        body += ['', '## Abstract', '', _literal(re.sub(r'\s+', ' ', p['summary']).strip())]
        if p.get('comment'):
            body += ['', f'*Comments:* {_literal(p["comment"])}']
        human = '## Notes\n\n<!-- Your reading notes. Everything outside the auto block is yours and survives rebuilds. -->\n'
        self._write_note(f'papers/{p["pid"]}.md', fm, '\n'.join(body), human)

    def topic_note(self, name: str, label: str, index: int | None, papers: list[dict]) -> None:
        fm = {
            'type': 'topic',
            'title': name,
            'label': label,
            'tier': 'focus' if label in FOCUS_LABELS else 'index',
            'index': index if index is not None else 0,
            'paper_count': len(papers),
            'review_every_days': REVIEW_DAYS,
        }
        body = [f'## Papers ({len(papers)})', '']
        by_date: dict[str, list[dict]] = {}
        for p in papers:
            by_date.setdefault(p['report_date'], []).append(p)
        for date in sorted(by_date, reverse=True):
            body.append(f'### [[{date}]]')
            for p in sorted(by_date[date], key=lambda x: x['number']):
                flag = ' ⭐' if p.get('_highlight') else ''
                tag = f' `{p["_method"]}`' if p.get('_method') else ''
                body.append(
                    f'- {self._paper_link(p)}{flag} — {self._short_authors(p["authors"])}{tag}'
                )
            body.append('')
        human = (
            f'# {name}\n\n## About\n\n<!-- Curated overview of this field: open questions, key results, '
            f'reading order. Update `reviewed:` in the frontmatter when you revise it. -->\n\n'
            f'reviewed: never\n'
        )
        self._write_note(
            f'topics/{_safe_name(name)}.md', fm, '\n'.join(body), human, human_first=True
        )

    def object_note(self, name: str, papers: list[dict]) -> None:
        fm = {'type': 'object', 'title': name, 'paper_count': len(papers)}
        body = [f'## Papers mentioning {name} ({len(papers)})', '']
        for p in sorted(papers, key=lambda x: (x['report_date'], x['number']), reverse=True):
            body.append(f'- [[{p["report_date"]}]] · {self._paper_link(p)}')
        human = f'# {name}\n\n## About\n\n<!-- What this source is and why it matters; keep it short. -->\n'
        self._write_note(
            f'objects/{_safe_name(name)}.md', fm, '\n'.join(body), human, human_first=True
        )

    def daily_note(self, date: str, papers: list[dict], digest: dict | None, raw_rel: str) -> None:
        fm = {
            'type': 'daily',
            'listing': date,
            'paper_count': len(papers),
            'digest': bool(digest),
            'source': raw_rel,
            'topics': sorted({TOPIC_NAME.get(t, t) for p in papers for t in p.get('_topics', [])}),
        }
        body = [f'# {date} — {len(papers)} papers', '']
        from core.render import REPORTS_DIR

        rel_report = os.path.relpath(
            os.path.join(REPORTS_DIR, f'arXiv_astro_ph_HE_daily_report_{date}.html'),
            os.path.join(WIKI_DIR, 'daily'),
        ).replace(os.sep, '/')
        body.append(f'[Open HTML report]({rel_report})')
        if digest and digest['highlights']:
            body += ['', '## Highlights', '']
            for n, text in digest['highlights'].items():
                p = next((x for x in papers if x['number'] == n), None)
                if p:
                    body.append(f'- {self._paper_link(p)} — {text}')
        body += ['', '## Field index', '']
        groups: dict[str, list[dict]] = {}
        for p in papers:
            for t in p.get('_topics') or [UNCLASSIFIED]:
                groups.setdefault(TOPIC_NAME.get(t, t), []).append(p)
        order = {name: i for i, (_, name) in enumerate(TOPICS)}
        for name in sorted(groups, key=lambda x: order.get(x, 99)):
            nums = ', '.join(
                f'[[{p["pid"]}|[{p["number"]}]]]'
                for p in sorted(groups[name], key=lambda x: x['number'])
            )
            body.append(f'- [[{name}]]: {nums}')
        body += ['', '## All papers', '']
        for p in sorted(papers, key=lambda x: x['number']):
            tag = f' `{p["_method"]}`' if p.get('_method') else ''
            body.append(
                f'{p["number"]}. {self._paper_link(p)} — {self._short_authors(p["authors"])}{tag}'
            )
        human = '## Notes\n\n<!-- Day-level remarks: what to follow up, who to tell. -->\n'
        self._write_note(f'daily/{date}.md', fm, '\n'.join(body), human)

    def home_note(
        self,
        topics: dict[str, list[dict]],
        dates: list[str],
        objects: dict[str, list[dict]],
        n_papers: int,
        lint_summary: str | None,
    ) -> None:
        fm = {
            'type': 'home',
            'title': 'Home',
            'paper_count': n_papers,
            'days': len(dates),
            'last_build': self.today,
        }
        body = [
            '# astro-ph.HE Wiki',
            '',
            f'{n_papers} papers · {len(dates)} listing days · last build {self.today}',
            '',
            'See [[MAINTENANCE]] for how this vault is kept healthy.',
            '',
            '## Topics',
            '',
        ]
        for label, name in TOPICS:
            ps = topics.get(label, [])
            if ps and label in FOCUS_LABELS:
                body.append(f'- [[{name}]] — {len(ps)}')
        body += ['', f'### {OTHER_GROUP} (index only)', '']
        for label, name in TOPICS:
            ps = topics.get(label, [])
            if ps and label not in FOCUS_LABELS:
                body.append(f'- [[{name}]] — {len(ps)}')
        if topics.get(UNCLASSIFIED):
            body.append(f'- [[{UNCLASSIFIED}]] — {len(topics[UNCLASSIFIED])}')
        cited = getattr(self, '_cited', [])
        if cited:
            body += ['', '## Most cited (SciX)', '']
            body += [
                f'- **{p["_cites"]["n"]}** · {self._paper_link(p)} · [[{p["report_date"]}]]'
                for p in cited[:25]
            ]
        body += ['', '## Recent days', '']
        body += [f'- [[{d}]]' for d in dates[:14]]
        weekly = (
            sorted(
                (f[:-3] for f in os.listdir(os.path.join(WIKI_DIR, 'weekly')) if f.endswith('.md')),
                reverse=True,
            )
            if os.path.isdir(os.path.join(WIKI_DIR, 'weekly'))
            else []
        )
        if weekly:
            body += ['', '## Weekly rollups', '']
            body.append(' · '.join(f'[[{w}]]' for w in weekly))
        top_objects = sorted(objects.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:40]
        if top_objects:
            body += ['', '## Most-discussed objects', '']
            body.append(' · '.join(f'[[{_safe_name(n)}]] ({len(ps)})' for n, ps in top_objects))
        # Sources discovered within the last year (date taken from the designation itself).
        latest = datetime.date.fromisoformat(dates[0]) if dates else datetime.date.today()
        cutoff = latest - datetime.timedelta(days=365)
        recent = [
            (n, ps)
            for n, ps in objects.items()
            if (dd := object_discovery_date(n)) is not None and dd >= cutoff
        ]
        recent.sort(key=lambda kv: (-len(kv[1]), kv[0]))
        if recent:
            body += [
                '',
                f'## Most-discussed recent objects (named since {cutoff.strftime("%b %Y")})',
                '',
                ' · '.join(f'[[{_safe_name(n)}]] ({len(ps)})' for n, ps in recent[:40]),
            ]
        if lint_summary:
            body += ['', '## Health', '', lint_summary]
        self._write_note('Home.md', fm, '\n'.join(body), '')

    # -- orchestration -----------------------------------------------------
    def run(self) -> dict:
        from core import citations, feedback
        from core.topics import FOCUS_LABELS

        verdicts = feedback.all_verdicts()
        notes = feedback.all_notes()
        cites = citations.all_counts()
        papers = corpus.all_papers()
        self._cited = sorted(
            (p for p in papers if cites.get(p['pid'], {}).get('n')),
            key=lambda p: (-cites[p['pid']]['n'], p['report_date']),
        )
        digests = load_digests()
        by_date: dict[str, list[dict]] = {}
        for p in papers:
            by_date.setdefault(p['report_date'], []).append(p)

        topics: dict[str, list[dict]] = {}
        objects: dict[str, list[dict]] = {}
        for date, day_papers in by_date.items():
            digest = digests.get(date)
            raw_rel = self._write_raw(date, day_papers)
            for p in day_papers:
                d = digest['papers'].get(p['number']) if digest else None
                entry_kind = 'none'
                if d and d.get('other'):
                    d = None  # abstract-only entry (filed under Other topics by design)
                    entry_kind = 'abstract'
                elif d:
                    entry_kind = 'full'
                # Guard against a report whose [N] does not match the cached order.
                if (
                    d
                    and d.get('arxiv_id')
                    and corpus.arxiv_pid('http://arxiv.org/abs/' + d['arxiv_id']) != p['pid']
                ):
                    d = None
                p_topics = digest['topics'].get(p['number'], []) if digest else []
                highlight = digest['highlights'].get(p['number']) if digest else None
                p['_verdict'] = verdicts.get(p['pid'], '')
                p['_note'] = notes.get(p['pid'], '')
                p['_cites'] = cites.get(p['pid'])
                if p['_verdict'] == 'dislike':  # dismissed: not a focus paper, never a highlight
                    p_topics = [t for t in p_topics if t not in FOCUS_LABELS]
                    highlight = None
                text = ' '.join([p['title'], p['summary'], *(d['fields'].values() if d else [])])
                objs = extract_objects(text)
                p['_topics'] = p_topics
                p['_method'] = d['method'] if d else ''
                p['_highlight'] = bool(highlight)
                self.paper_note(p, d, p_topics, highlight, objs, raw_rel, entry_kind)
                for t in p_topics or [UNCLASSIFIED]:
                    topics.setdefault(t, []).append(p)
                for o in objs:
                    objects.setdefault(o, []).append(p)
            self.daily_note(date, day_papers, digest, raw_rel)

        for i, (label, name) in enumerate(TOPICS, start=1):
            if topics.get(label):
                self.topic_note(name, label, i, topics[label])
        if topics.get(UNCLASSIFIED):
            self.topic_note(UNCLASSIFIED, UNCLASSIFIED, None, topics[UNCLASSIFIED])
        for name, ps in objects.items():
            self.object_note(name, ps)

        self.maintenance_note()
        dates = sorted(by_date, reverse=True)
        self.home_note(topics, dates, objects, len(papers), None)

        summary = {
            'op': self.op_id,
            'ts': datetime.datetime.now().isoformat(timespec='seconds'),
            'command': 'build' + (' --dry-run' if self.dry_run else ''),
            'papers': len(papers),
            'days': len(dates),
            'created': len(self.created),
            'updated': len(self.updated),
            'unchanged': self.unchanged,
            'created_paths': self.created[:50],
            'updated_paths': self.updated[:50],
        }
        if not self.dry_run:
            append_log(summary)
        return summary

    def maintenance_note(self) -> None:
        fm = {'type': 'meta', 'title': 'MAINTENANCE', 'review_every_days': REVIEW_DAYS}
        body = f"""# How this wiki is maintained

This vault is generated from the arXiv astro-ph.HE daily reports and kept healthy the way
[claude-obsidian](https://github.com/AgriciDaniel/claude-obsidian) keeps a knowledge base:
plain Markdown you own, preserved sources, journaled operations, and a linter.

## Ownership rule

Every note has exactly one machine-owned block:

```
{AUTO_START}
…regenerated by `python wiki.py build`…
{AUTO_END}
```

- Write anywhere **outside** the block (the `## Notes` / `## About` sections exist for that). It survives every rebuild.
- Do not edit inside the block; the next build overwrites it and reports the note as *updated*.
- Frontmatter keys the builder owns (`type`, `title`, `listing`, `topics`, `objects`, `status`, …) are rewritten; keys you add are kept. `created` is never changed.

## Daily cycle (automatic)

`run_report.sh` → fetch → LLM digest → `build_site.py` → `wiki.py build` → `wiki.py lint`.
Each build appends one line to `.log/operations.jsonl` (operation id, counts, changed paths) and
stores the day's source records as a content-addressed copy in `.raw/<date>.<sha12>.json`;
paper notes carry `source` and `source_sha256` so every claim traces back to its abstract.

## Weekly cycle

`python wiki.py fold` writes `weekly/<ISO week>.md`: an extractive rollup (counts per topic,
highlights, newly seen objects, build/lint log of the week). Nothing is paraphrased; every
line links to the daily or paper note it came from.

## Review cycle ({REVIEW_DAYS} days)

Topic and object notes have a human `## About` section with a `reviewed: YYYY-MM-DD` line
(`reviewed: never` until you write one). `wiki.py lint` lists notes whose review is older than
{REVIEW_DAYS} days so curated overviews do not silently rot. Change the window with `WIKI_REVIEW_DAYS`.

## Linter

`python wiki.py lint [--strict]` reports:

- **dead links** — double-bracket wikilinks whose target note does not exist
- **orphans** — notes nothing links to (Home / MAINTENANCE excluded)
- **metadata gaps** — required frontmatter missing for the note type
- **stale indexes** — notes whose auto block differs from what a fresh build would write (run `build`)
- **missing report entries** — papers whose listing day has no entry at all (abstract-only *Other topics* entries are counted separately, not flagged)
- **overdue reviews** — curated sections older than the review window

`--strict` exits non-zero when dead links, metadata gaps or stale indexes exist, for CI or cron.

## Recovery

Notes are plain files: use `git` (or Obsidian's file recovery) for history. A build never deletes
notes; retired papers or objects simply stop being linked and show up as orphans in `lint`.
"""
        self._write_note('MAINTENANCE.md', fm, body, '')


def append_log(entry: dict) -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(LOG_PATH, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')


def read_log() -> list[dict]:
    if not os.path.exists(LOG_PATH):
        return []
    out = []
    with open(LOG_PATH, encoding='utf-8') as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


# --------------------------------------------------------------------------- lint
_REQUIRED = {
    'paper': ['type', 'arxiv', 'title', 'listing', 'topics', 'source_sha256'],
    'topic': ['type', 'title', 'paper_count'],
    'object': ['type', 'title', 'paper_count'],
    'daily': ['type', 'listing', 'paper_count', 'source'],
    'weekly': ['type', 'title', 'week'],
    'home': ['type', 'title'],
    'meta': ['type', 'title'],
}


def _iter_notes() -> dict[str, str]:
    """``{relative path: text}`` for every Markdown note in the vault."""
    notes = {}
    for root, dirs, files in os.walk(WIKI_DIR):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for fn in files:
            if fn.endswith('.md'):
                path = os.path.join(root, fn)
                with open(path, encoding='utf-8') as f:
                    notes[os.path.relpath(path, WIKI_DIR)] = f.read()
    return notes


def lint(stale_check: bool = True) -> dict:
    notes = _iter_notes()
    names = {os.path.splitext(os.path.basename(rel))[0]: rel for rel in notes}
    rel_set = set(notes)
    inbound: dict[str, int] = dict.fromkeys(notes, 0)
    dead: list[tuple[str, str]] = []
    gaps: list[tuple[str, str]] = []
    no_digest: list[str] = []
    abstract_only = 0
    overdue: list[tuple[str, str]] = []
    today = datetime.date.today()

    for rel, text in notes.items():
        fm, body = _parse_frontmatter(text)
        ntype = fm.get('type', '')
        for key in _REQUIRED.get(ntype, ['type']):
            if key not in fm or fm[key] in ('', [], None):
                gaps.append((rel, key))
        if ntype == 'paper':
            kind = fm.get('entry') or ('full' if fm.get('digest') else 'none')
            if kind == 'none':
                no_digest.append(rel)
            elif kind == 'abstract':
                abstract_only += 1
        if ntype in ('topic', 'object'):
            m = re.search(r'^reviewed:\s*(\S+)', body, re.M)
            val = m.group(1) if m else 'never'
            try:
                age = (today - datetime.date.fromisoformat(str(val))).days
            except ValueError:
                # never reviewed: give the note one review window from its creation
                try:
                    age = (today - datetime.date.fromisoformat(str(fm.get('created', '')))).days
                except ValueError:
                    age = REVIEW_DAYS + 1
            if age > REVIEW_DAYS:
                overdue.append((rel, val))
        for target in _WIKILINK_RE.findall(text):
            target = target.strip()
            if target in rel_set or f'{target}.md' in rel_set:
                hit = target if target in rel_set else f'{target}.md'
            else:
                hit = names.get(os.path.basename(target))
            if hit is None:
                dead.append((rel, target))
            elif hit != rel:
                inbound[hit] += 1

    orphans = sorted(
        rel for rel, n in inbound.items() if n == 0 and rel not in ('Home.md', 'MAINTENANCE.md')
    )

    stale: list[str] = []
    if stale_check:
        probe = Build(dry_run=True)
        probe.run()
        stale = sorted(probe.updated)

    result = {
        'notes': len(notes),
        'dead_links': dead,
        'orphans': orphans,
        'metadata_gaps': gaps,
        'stale_indexes': stale,
        'missing_digests': sorted(no_digest),
        'abstract_only': abstract_only,
        'overdue_reviews': overdue,
    }
    append_log(
        {
            'op': uuid.uuid4().hex[:12],
            'ts': datetime.datetime.now().isoformat(timespec='seconds'),
            'command': 'lint',
            'notes': len(notes),
            **{k: len(v) for k, v in result.items() if isinstance(v, list)},
        }
    )
    return result


def format_lint(r: dict) -> str:
    lines = [f'{r["notes"]} notes']

    def section(title, items, fmt):
        lines.append(f'{title}: {len(items)}')
        for it in items[:40]:
            lines.append('  ' + fmt(it))
        if len(items) > 40:
            lines.append(f'  … {len(items) - 40} more')

    section('dead links', r['dead_links'], lambda x: f'{x[0]} -> [[{x[1]}]]')
    section('orphans', r['orphans'], lambda x: x)
    section('metadata gaps', r['metadata_gaps'], lambda x: f'{x[0]}: missing {x[1]}')
    section('stale indexes (run build)', r['stale_indexes'], lambda x: x)
    section('missing report entries', r['missing_digests'], lambda x: x)
    lines.append(f'abstract-only (Other topics, by design): {r.get("abstract_only", 0)}')
    section(
        f'overdue reviews (> {REVIEW_DAYS} d)',
        r['overdue_reviews'],
        lambda x: f'{x[0]} (reviewed: {x[1]})',
    )
    return '\n'.join(lines)


# --------------------------------------------------------------------------- fold (weekly rollup)
def fold(week: str | None = None) -> str:
    """Write ``weekly/<ISO week>.md`` as an extractive rollup; returns the relative path."""
    today = datetime.date.today()
    if week:
        year, wk = week.upper().split('-W')
        monday = datetime.date.fromisocalendar(int(year), int(wk), 1)
    else:
        monday = today - datetime.timedelta(days=today.weekday())
    sunday = monday + datetime.timedelta(days=6)
    week_id = f'{monday.isocalendar()[0]}-W{monday.isocalendar()[1]:02d}'
    days = [
        p
        for p in corpus.all_papers()
        if monday.isoformat() <= p['report_date'] <= sunday.isoformat()
    ]
    digests = load_digests()
    by_date: dict[str, list[dict]] = {}
    for p in days:
        by_date.setdefault(p['report_date'], []).append(p)

    topic_counts: dict[str, int] = {}
    highlights: list[str] = []
    objects: dict[str, set] = {}
    for date, ps in sorted(by_date.items()):
        d = digests.get(date)
        for p in ps:
            ts = d['topics'].get(p['number'], []) if d else []
            for t in ts or [UNCLASSIFIED]:
                name = TOPIC_NAME.get(t, t)
                topic_counts[name] = topic_counts.get(name, 0) + 1
            if d and p['number'] in d['highlights']:
                highlights.append(
                    f'- [[{date}]] · [[{p["pid"]}|{clean_title(p["title"])}]] — {d["highlights"][p["number"]]}'
                )
            fields = d['papers'].get(p['number'], {}).get('fields', {}) if d else {}
            for o in extract_objects(' '.join([p['title'], p['summary'], *fields.values()])):
                objects.setdefault(o, set()).add(p['pid'])
    # objects first seen this week = not present in papers before monday
    earlier = [p for p in corpus.all_papers() if p['report_date'] < monday.isoformat()]
    seen_before = set()
    for p in earlier:
        seen_before.update(extract_objects(p['title'] + ' ' + p['summary']))
    new_objects = sorted(o for o in objects if o not in seen_before)

    log = [
        e for e in read_log() if monday.isoformat() <= e.get('ts', '')[:10] <= sunday.isoformat()
    ]

    fm = {
        'type': 'weekly',
        'title': week_id,
        'week': week_id,
        'from': monday.isoformat(),
        'to': sunday.isoformat(),
        'paper_count': len(days),
        'days': sorted(by_date),
    }
    body = [
        f'# Week {week_id} ({monday} → {sunday})',
        '',
        f'{len(days)} papers over {len(by_date)} listing days: '
        + ', '.join(f'[[{d}]]' for d in sorted(by_date)),
        '',
        '## Papers per topic',
        '',
    ]
    order = {name: i for i, (_, name) in enumerate(TOPICS)}
    for name in sorted(topic_counts, key=lambda x: (order.get(x, 99), x)):
        body.append(f'- [[{name}]] — {topic_counts[name]}')
    if highlights:
        body += ['', '## Highlights of the week', '', *highlights]
    if new_objects:
        body += [
            '',
            '## Objects first seen this week',
            '',
            ' · '.join(f'[[{_safe_name(o)}]]' for o in new_objects),
        ]
    if log:
        body += ['', '## Operations log', '']
        for e in log[-30:]:
            if e.get('command', '').startswith('build'):
                body.append(
                    f'- {e["ts"]} build `{e["op"]}`: +{e.get("created", 0)} / ~{e.get("updated", 0)} / ={e.get("unchanged", 0)}'
                )
            elif e.get('command') == 'lint':
                body.append(
                    f'- {e["ts"]} lint: dead {e.get("dead_links", 0)}, orphans {e.get("orphans", 0)}, '
                    f'gaps {e.get("metadata_gaps", 0)}, stale {e.get("stale_indexes", 0)}, '
                    f'overdue {e.get("overdue_reviews", 0)}'
                )
    b = Build()
    b._write_note(
        f'weekly/{week_id}.md',
        fm,
        '\n'.join(body),
        '## Notes\n\n<!-- Weekly reflections, decisions, who was told what. -->\n',
    )
    append_log(
        {
            'op': b.op_id,
            'ts': datetime.datetime.now().isoformat(timespec='seconds'),
            'command': f'fold {week_id}',
            'papers': len(days),
        }
    )
    return f'weekly/{week_id}.md'


# --------------------------------------------------------------------------- HTML export
HTML_DIR = os.path.join(os.path.dirname(FRAGMENTS_DIR), 'wiki')  # reports/wiki
_CALLOUT_RE = re.compile(r'^> \[!(\w+)\]\s*(.*)\n((?:> ?.*\n?)*)', re.M)
_MD_LINK_REPORT_RE = re.compile(r'\]\(\.\./\.\./reports/')


def _html_path(rel_md: str) -> str:
    return rel_md[:-3] + '.html'


def _rel(from_rel: str, to_rel: str) -> str:
    from urllib.parse import quote

    rel = os.path.relpath(to_rel, os.path.dirname(from_rel) or '.').replace(os.sep, '/')
    return quote(rel, safe='/.-_~')


def _render_markdown(md: str) -> str:
    import markdown

    def callout(m: re.Match) -> str:
        kind, title, body = m.group(1).lower(), m.group(2), m.group(3)
        text = '\n'.join(
            line[2:] if line.startswith('> ') else line[1:] for line in body.splitlines()
        )
        return (
            f'<div class="callout callout-{kind}"><p class="callout-title">{title or kind.title()}</p>\n\n'
            f'{text}\n</div>\n'
        )

    md = _CALLOUT_RE.sub(callout, md)
    return markdown.markdown(md, extensions=['tables', 'fenced_code', 'sane_lists', 'md_in_html'])


def _wiki_shell(
    title: str, body: str, rel_root: str, to_reports: str, meta: str, extra_nav: str = ''
) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_html.escape(title)} · astro-ph.HE Wiki</title>
<link rel="stylesheet" href="{rel_root}wiki.css">
</head>
<body>
<nav class="topnav">
  <a href="{rel_root}Home.html"><strong>📚 astro-ph.HE Wiki</strong></a>
  <a href="{rel_root}Home.html#topics">Topics</a>
  <a href="{rel_root}Home.html#recent-days">Days</a>
  <a href="{rel_root}Home.html#weekly-rollups">Weeks</a>
  <a href="{rel_root}Home.html#most-discussed-objects">Objects</a>
  <a href="{rel_root}MAINTENANCE.html">Maintenance</a>
  <span class="spacer"></span>
  {extra_nav}
  <a class="rl" data-date="" data-anchor="" href="{to_reports}index.html">Reports ↗</a>
</nav>
<main class="note">
{meta}
{body}
</main>
<script>
// Inside the FastAPI web UI (/wiki/...), report links go to /r/<date>#pN; on the static site
// they open the tabbed index at index.html#<date>/pN.
(function () {{
  var server = window.location.pathname.indexOf('/wiki/') === 0;
  document.querySelectorAll('a.rl').forEach(function (a) {{
    var d = a.dataset.date, p = a.dataset.anchor, w = a.dataset.week;
    if (w) {{ a.href = server ? ('/s/week-' + w) : ('{to_reports}index.html#week/' + w); return; }}
    if (server) a.href = d ? ('/r/' + d + (p ? '#' + p : '')) : '/';
    else if (d) a.href = '{to_reports}index.html#day/' + d + (p ? '/' + p : '');
  }});
}})();
</script>
</body>
</html>
"""


_WIKI_CSS = """
:root { color-scheme: light dark; --bg:#fbfbfc; --surface:#fff; --alt:#f4f6f9; --text:#1f2933; --muted:#6b7280;
        --primary:#1f4e8c; --border:#e5e7eb; --tip:#2f855a; --tipbg:#e3f2eb; --note:#1f4e8c; --notebg:#e4eef9; }
@media (prefers-color-scheme: dark) { :root { --bg:#0f172a; --surface:#1e293b; --alt:#172033; --text:#e2e8f0; --muted:#94a3b8;
        --primary:#93c5fd; --border:#334155; --tip:#86efac; --tipbg:#14291c; --note:#93c5fd; --notebg:#1e3a5f; } }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--text); font:15px/1.6 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; }
.topnav { display:flex; flex-wrap:wrap; gap:14px; align-items:center; padding:12px 24px; background:var(--surface); border-bottom:1px solid var(--border); position:sticky; top:0; }
.topnav a { color:var(--text); text-decoration:none; font-size:.9rem; } .topnav a:hover { color:var(--primary); }
.topnav .spacer { flex:1; }
.topnav .btn { padding:4px 10px; border:1px solid var(--border); border-radius:8px; background:var(--alt); }
main.note { max-width: 900px; margin: 0 auto; padding: 24px 24px 80px; }
.meta { display:flex; flex-wrap:wrap; gap:8px; margin: 0 0 14px; font-size:.8rem; color:var(--muted); }
.meta span { padding:1px 8px; border:1px solid var(--border); border-radius:999px; background:var(--surface); }
h1 { font-size:1.55rem; line-height:1.3; margin:.2em 0 .6em; } h2 { font-size:1.15rem; margin:1.6em 0 .5em; border-bottom:1px solid var(--border); padding-bottom:4px; }
h3 { font-size:1rem; margin:1.2em 0 .4em; color:var(--muted); }
a { color:var(--primary); text-decoration:none; } a:hover { text-decoration:underline; }
a.dead { color:var(--muted); border-bottom:1px dashed var(--muted); }
code { background:var(--alt); padding:1px 5px; border-radius:4px; font-size:.9em; }
pre { background:var(--alt); padding:12px; border-radius:8px; overflow-x:auto; }
.callout { border-left:4px solid var(--note); background:var(--notebg); padding:10px 14px; border-radius:8px; margin:14px 0; }
.callout-tip { border-color:var(--tip); background:var(--tipbg); }
.callout-title { margin:0 0 4px; font-weight:700; }
ul { padding-left: 22px; } li { margin: 4px 0; }
table { border-collapse:collapse; } td, th { border-bottom:1px solid var(--border); padding:4px 8px; }
hr { border:0; border-top:1px solid var(--border); margin:24px 0; }
"""


_DAILY_REPORT_A_RE = re.compile(
    r'<a href="([^"]*?)arXiv_astro_ph_HE_daily_report_(\d{4}-\d{2}-\d{2})\.html(#p\d+)?">'
)


def export_html() -> int:
    """Render every note to ``reports/wiki/*.html`` with resolved wikilinks and report links."""
    notes = _iter_notes()
    names = {os.path.splitext(os.path.basename(rel))[0]: rel for rel in notes}
    os.makedirs(HTML_DIR, exist_ok=True)
    with open(os.path.join(HTML_DIR, 'wiki.css'), 'w', encoding='utf-8') as f:
        f.write(_WIKI_CSS)
    written = 0
    for rel, text in notes.items():
        fm, body = _parse_frontmatter(text)
        out_rel = _html_path(rel)
        depth = out_rel.count('/')
        rel_root = '../' * depth
        to_reports = '../' * (depth + 1)

        def link(m: re.Match, out_rel: str = out_rel) -> str:
            target, alias = m.group(1).strip(), (m.group(2) or m.group(1)).strip()
            if target in notes:
                hit = target
            elif f'{target}.md' in notes:
                hit = f'{target}.md'
            else:
                hit = names.get(os.path.basename(target))

            if hit is None:
                return f'<a class="dead" title="missing note">{_html.escape(alias)}</a>'
            return f'<a href="{_rel(out_rel, _html_path(hit))}">{_html.escape(alias)}</a>'

        body = re.sub(r'\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]*))?\]\]', link, body)
        body = _MD_LINK_REPORT_RE.sub(f']({to_reports}', body)
        body = body.replace(AUTO_START, '').replace(AUTO_END, '')
        html_body = _render_markdown(body)
        html_body = _DAILY_REPORT_A_RE.sub(
            lambda m, to_reports=to_reports: (
                f'<a class="rl" data-date="{m.group(2)}" data-anchor="{(m.group(3) or "#")[1:]}" '
                f'href="{to_reports}index.html#day/{m.group(2)}{"/" + m.group(3)[1:] if m.group(3) else ""}">'
            ),
            html_body,
        )

        # per-type metadata strip and report button
        chips = []
        extra_nav = ''
        ntype = fm.get('type', '')
        if ntype == 'paper':
            chips += [
                f'listing {fm.get("listing", "")}',
                f'[{fm.get("report_number", "")}]',
                fm.get('method') or 'abstract only',
                fm.get('status', ''),
            ]
            extra_nav = (
                f'<a class="rl btn" data-date="{fm.get("listing", "")}" data-anchor="p{fm.get("report_number", "")}" '
                f'href="{to_reports}index.html#day/{fm.get("listing", "")}/p{fm.get("report_number", "")}">Open in report →</a>'
            )
        elif ntype == 'daily':
            chips += [
                f'{fm.get("paper_count", "")} papers',
                'digest' if fm.get('digest') else 'no digest',
            ]
            extra_nav = (
                f'<a class="rl btn" data-date="{fm.get("listing", "")}" data-anchor="" '
                f'href="{to_reports}index.html#day/{fm.get("listing", "")}">Open daily report →</a>'
            )
        elif ntype in ('topic', 'object'):
            chips += [f'{fm.get("paper_count", "")} papers']
        elif ntype == 'weekly':
            chips += [
                f'{fm.get("from", "")} → {fm.get("to", "")}',
                f'{fm.get("paper_count", "")} papers',
            ]
            extra_nav = (
                f'<a class="rl btn" data-week="{fm.get("week", "")}" '
                f'href="{to_reports}index.html#week/{fm.get("week", "")}">Week summary →</a>'
            )
        chips = [c for c in chips if c]
        if fm.get('updated'):
            chips.append(f'updated {fm["updated"]}')
        meta = (
            '<div class="meta">'
            + ''.join(f'<span>{_html.escape(str(c))}</span>' for c in chips)
            + '</div>'
            if chips
            else ''
        )
        title = str(fm.get('title') or os.path.splitext(os.path.basename(rel))[0])
        page = _wiki_shell(title, html_body, rel_root, to_reports, meta, extra_nav)
        out_path = os.path.join(HTML_DIR, out_rel)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(page)
        written += 1
    return written
