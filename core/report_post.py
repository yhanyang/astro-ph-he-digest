"""Post-processing of the LLM report body.

* :func:`finalize_report` appends an "Other topics" section with title /
  authors / abstract for every paper that received no Part 3 entry, so a
  report always lists all papers of the day. Those entries carry
  ``class="paper-item paper-other"`` and can later be upgraded to a full
  digest by :mod:`core.promote`.
* :func:`relabel_legacy_index` rewrites the field index of reports produced
  under the former 12-category taxonomy into the current one.
"""

from __future__ import annotations

import html as _html
import re

from core.prompt import _arxiv_display_id, _render_status_badge
from core.topics import FOCUS_LABELS, OTHER_GROUP, OTHER_LABEL, TOPICS, legacy_to_new, v2_to_v3

EFXT_LABEL = 'Extragalactic Fast X-ray Transients (EFXT / FXT)'
_EFXT_RE = re.compile(r'fast[- ]x-?ray transients?|\bE?FXTs?\b|\bEP\d{6}[a-z]?\b', re.I)
_EFXT_EXCLUDE_RE = re.compile(
    r'\bSFXTs?\b|supergiant fast[- ]x-?ray', re.I
)  # Galactic HMXBs, not EFXTs

_PAPER_ID_RE = re.compile(r'<div class="paper-item(?: [^"]*)?" id="p(\d+)"')
_INDEX_BOX_RE = re.compile(r'<div class="index-box">(.*?)</div>', re.S)
_INDEX_LINE_RE = re.compile(r'<p>\s*<strong>(.*?):?\s*</strong>(.*?)</p>', re.S)
_ANCHOR_NUM_RE = re.compile(r'href="#p(\d+)"')
_FIRST_OTHER_ITEM_RE = re.compile(r'<div class="other-box">')
_ORDER = {label: i for i, (label, _) in enumerate(TOPICS)}


def digested_numbers(report: str) -> set[int]:
    return {int(n) for n in _PAPER_ID_RE.findall(report)}


def parse_index(report: str) -> dict[str, list[int]]:
    """``{label: [numbers]}`` from the index box (labels as written)."""
    m = _INDEX_BOX_RE.search(report)
    out: dict[str, list[int]] = {}
    if not m:
        return out
    for label, body in _INDEX_LINE_RE.findall(m.group(1)):
        label = _html.unescape(label).strip().rstrip(':')
        out[label] = [int(n) for n in _ANCHOR_NUM_RE.findall(body)]
    return out


def render_index(index: dict[str, list[int]]) -> str:
    lines = ['<div class="index-box">', '<h3>Field Index</h3>']
    for label in sorted(index, key=lambda x: _ORDER.get(x, 99)):
        nums = sorted(set(index[label]))
        if not nums:
            continue
        links = ', '.join(f'<a href="#p{n}">[{n}]</a>' for n in nums)
        lines.append(f'<p><strong>{_html.escape(label, quote=False)}:</strong> {links}</p>')
    lines.append('</div>')
    return '\n'.join(lines)


def _other_entry(n: int, paper: dict) -> str:
    badge = _render_status_badge(paper)
    badge_html = f' {badge}' if badge else ''
    abstract = _html.escape(re.sub(r'\s+', ' ', paper.get('summary', '')).strip(), quote=False)
    return (
        f'<div class="paper-item paper-other" id="p{n}">\n'
        f'<h3>[{n}] <a href="{paper["url"]}">{_arxiv_display_id(paper["url"])}</a>{badge_html}</h3>\n'
        f'<p><strong>Title:</strong>{_html.escape(paper["title"].replace(chr(10), " ").strip(), quote=False)}</p>\n'
        f'<p><strong>Authors:</strong>{_html.escape(paper.get("authors", ""), quote=False)}</p>\n'
        f'<p class="other-cats"><strong>Categories:</strong>{", ".join(paper.get("categories", []))}</p>\n'
        f'<details class="other-abstract"><summary>Abstract</summary><p>{abstract}</p></details>\n'
        f'</div>'
    )


def finalize_report(report: str, papers: list[dict]) -> str:
    """Append abstract-only entries for every paper without a Part 3 entry.

    Idempotent: a report that already lists every paper is returned unchanged
    (apart from making sure the index has an "Other topics" line for them).
    """
    report = report.replace('```html', '').replace('```', '').strip()
    have = digested_numbers(report)
    missing = [i for i in range(1, len(papers) + 1) if i not in have]
    if not missing:
        return report
    index = parse_index(report)
    others = set(index.get(OTHER_LABEL, []))
    filed = {n for label, nums in index.items() if label != OTHER_LABEL for n in nums}
    for n in missing:
        if n not in filed:
            others.add(n)
    index[OTHER_LABEL] = sorted(others)
    m = _INDEX_BOX_RE.search(report)
    report = (
        (report[: m.start()] + render_index(index) + report[m.end() :])
        if m
        else render_index(index) + '\n' + report
    )
    entries = '\n'.join(_other_entry(n, papers[n - 1]) for n in missing)
    if not have:  # index-only day: nothing was read in depth yet
        title, count = (
            'Index-only report',
            f'{len(missing)} papers · filed by keyword, no digest yet',
        )
        hint = (
            'No LLM digest for this day yet. Generate it with <code>./run_report.sh --date &lt;date&gt;</code> '
            'or read single papers in depth with the ▲ button / <code>python promote.py</code>.'
        )
    else:
        title, count = OTHER_GROUP, f'{len(missing)} papers · index only: title and abstract'
        hint = (
            'Filed under index-only topics (not read in depth). Use the ▲ button (web UI) or '
            '<code>python promote.py &lt;date&gt; &lt;arXiv id&gt;</code> to generate a full digest.'
        )
    section = (
        '<div class="other-box">\n'
        f'<h3>{title} <span class="other-count">{count}</span></h3>\n'
        f'<p class="other-hint">{hint}</p>\n'
        '</div>\n' + entries
    )
    return report.rstrip() + '\n' + section


def relabel_legacy_index(report: str, papers: list[dict]) -> str:
    """Convert a 12-category index to the current taxonomy, keeping all entries."""
    index = parse_index(report)
    if not index or all(label in _ORDER for label in index):
        return report  # already current
    new: dict[str, set[int]] = {}
    for label, nums in index.items():
        for n in nums:
            p = papers[n - 1] if 0 < n <= len(papers) else {}
            text = ' '.join([p.get('title', ''), p.get('summary', '')])
            for target in legacy_to_new(label, text):
                new.setdefault(target, set()).add(n)
    # a paper in a focus category must not also sit in Other
    focus_nums = {n for label, nums in new.items() if label != OTHER_LABEL for n in nums}
    if OTHER_LABEL in new:
        new[OTHER_LABEL] -= focus_nums
    m = _INDEX_BOX_RE.search(report)
    return (
        report[: m.start()]
        + render_index({k: sorted(v) for k, v in new.items()})
        + report[m.end() :]
    )


def file_by_keyword(
    report: str, papers: list[dict], label: str = EFXT_LABEL, pattern: re.Pattern = _EFXT_RE
) -> tuple[str, list[int]]:
    """Add every paper whose title/abstract matches ``pattern`` to ``label`` in the field index.

    Used to retro-fit a newly added focus topic onto existing reports without an LLM call.
    A paper that was only under "Other topics" is moved (its entry stays abstract-only and
    can be promoted later); papers already in focus topics simply gain the extra label.
    Returns ``(report, numbers_added)``.
    """
    index = parse_index(report)
    if not index:
        return report, []
    current = set(index.get(label, []))
    added: list[int] = []
    for n, p in enumerate(papers, start=1):
        text = f'{p.get("title", "")} {p.get("summary", "")}'
        if (
            n in current
            or not pattern.search(text)
            or (pattern is _EFXT_RE and _EFXT_EXCLUDE_RE.search(text))
        ):
            continue
        index.setdefault(label, []).append(n)
        if n in index.get(OTHER_LABEL, []):
            index[OTHER_LABEL].remove(n)
        added.append(n)
    if not added:
        return report, []
    index = {k: v for k, v in index.items() if v}
    m = _INDEX_BOX_RE.search(report)
    return report[: m.start()] + render_index(index) + report[m.end() :], added


def remap_index(report: str, papers: list[dict], mapper=v2_to_v3) -> tuple[str, dict[str, int]]:
    """Re-file every index line through ``mapper(old_label, paper_text)``.

    Returns the updated report and ``{new_label: count}``. Entries are untouched.
    """
    index = parse_index(report)
    if not index:
        return report, {}
    new: dict[str, set[int]] = {}
    for label, nums in index.items():
        for n in nums:
            p = papers[n - 1] if 0 < n <= len(papers) else {}
            text = f'{p.get("title", "")} {p.get("summary", "")}'
            for target in mapper(label, text):
                new.setdefault(target, set()).add(n)
    m = _INDEX_BOX_RE.search(report)
    out = (
        report[: m.start()]
        + render_index({k: sorted(v) for k, v in new.items()})
        + report[m.end() :]
    )
    return out, {k: len(v) for k, v in new.items()}


_HL_BOX_RE = re.compile(r'<div class="highlight-box">(.*?)</div>\n?', re.S)
_HL_LINE_RE = re.compile(r'<p>\s*<a href="#p(\d+)">\[\d+\]</a>.*?</p>', re.S)


def filter_highlights(report: str) -> tuple[str, int, int]:
    """Keep only highlights of papers filed under a focus topic.

    Returns ``(report, before, after)``; the whole highlight box is removed when
    nothing remains, as the prompt rules require.
    """
    m = _HL_BOX_RE.search(report)
    if not m:
        return report, 0, 0
    index = parse_index(report)
    focus = {n for label, nums in index.items() if label in FOCUS_LABELS for n in nums}
    inner = m.group(1)
    lines = list(_HL_LINE_RE.finditer(inner))
    kept = [mm.group(0) for mm in lines if int(mm.group(1)) in focus]
    if len(kept) == len(lines):
        return report, len(lines), len(lines)
    if not kept:
        return report[: m.start()] + report[m.end() :], len(lines), 0
    h3 = re.search(r'<h3>.*?</h3>', inner, re.S)
    box = (
        '<div class="highlight-box">\n'
        + (h3.group(0) + '\n' if h3 else '')
        + '\n'.join(kept)
        + '\n</div>\n'
    )
    return report[: m.start()] + box + report[m.end() :], len(lines), len(kept)


_OTHER_ENTRY_RE = re.compile(r'<div class="paper-item paper-other" id="p\d+">.*?</div>\n?', re.S)
_OTHER_BOX_RE = re.compile(r'<div class="other-box">.*?</div>\n?', re.S)


def strip_other_entries(report: str) -> str:
    """Remove the generated Other-topics box and abstract-only entries (``finalize_report`` re-adds them)."""
    return _OTHER_ENTRY_RE.sub('', _OTHER_BOX_RE.sub('', report)).rstrip() + '\n'


_ANY_ENTRY_RE = r'<div class="paper-item(?: [^"]*)?" id="p{n}">.*?</div>\n?'
DISMISSED_TITLE = 'Dismissed papers'


def apply_feedback(
    report: str, papers: list[dict], verdicts: dict[str, str], notes: dict[str, str] | None = None
) -> str:
    """Mark liked entries and move disliked ones into a collapsed "Dismissed papers" box.

    Runs at render time on a finalized body; the stored fragment is never changed, so
    clearing a verdict and re-rendering restores the original layout.
    """
    from core.corpus import arxiv_pid

    notes = notes or {}
    dismissed: list[tuple[int, str]] = []
    for n, p in enumerate(papers, start=1):
        pid = arxiv_pid(p.get('url', '')) or ''
        verdict = verdicts.get(pid)
        note = notes.get(pid)
        if not verdict and not note:
            continue
        m = re.search(_ANY_ENTRY_RE.format(n=n), report, re.S)
        if not m:
            continue
        entry = m.group(0)
        if note:
            marked = entry.rstrip()
            assert marked.endswith('</div>')
            marked = (
                marked[: -len('</div>')]
                + f'<p class="paper-note"><strong>Note:</strong>{_html.escape(note, quote=False)}</p>\n</div>\n'
            )
            report = report.replace(entry, marked, 1)
            entry = marked
        if not verdict:
            continue
        if verdict == 'like':
            report = report.replace(
                entry, entry.replace('class="paper-item', 'class="paper-item paper-liked', 1), 1
            )
        elif verdict == 'dislike':
            report = report.replace(entry, '', 1)
            dismissed.append(
                (n, entry.replace('class="paper-item', 'class="paper-item paper-ignored', 1))
            )
    if dismissed:
        report = (
            report.rstrip()
            + '\n<div class="ignored-box">\n'
            + f'<details><summary><strong>{DISMISSED_TITLE}</strong> <span class="other-count">{len(dismissed)} · not followed; '
            'excluded from focus counts, highlights and summaries</span></summary>\n'
            + ''.join(e for _, e in sorted(dismissed))
            + '</details>\n</div>\n'
        )
    return report


_IGNORED_BOX_OPEN_RE = re.compile(
    r'<div class="ignored-box">\n<details><summary>.*?</summary>\n', re.S
)


def strip_feedback(report: str) -> str:
    """Undo ``apply_feedback`` marks (used to repair fragments that were saved with them)."""
    if _IGNORED_BOX_OPEN_RE.search(report):
        report = _IGNORED_BOX_OPEN_RE.sub('', report)
        report = re.sub(r'</details>\n</div>\n?\s*$', '', report)
    # stray closing pair left by an earlier repair (box opener already gone)
    report = re.sub(r'(</div>)\n</details>\n</div>\n?\s*$', r'\1', report)
    return report.replace(' paper-ignored', '').replace(' paper-liked', '')


_ENTRY_H3_RE = r'(<div class="paper-item[^"]*" id="p{n}"[^>]*>\s*<h3>.*?)(</h3>)'


def apply_citations(report: str, papers: list[dict], cites: dict[str, dict]) -> str:
    """Add a SciX citation badge to every entry with at least one citation (render time only).

    ``cites`` is ``core.citations.all_counts()``; the badge links to the SciX abstract page and
    the entry gets ``data-cites="N"``.
    """
    from core.citations import scix_url
    from core.corpus import arxiv_pid

    for n, p in enumerate(papers, start=1):
        c = cites.get(arxiv_pid(p.get('url', '')) or '')
        if not c or not c.get('n'):
            continue
        m = re.search(_ENTRY_H3_RE.format(n=n), report, re.S)
        if not m:
            continue
        head = m.group(1)
        if 'class="cite-tag"' in head:
            continue
        word = 'citation' if c['n'] == 1 else 'citations'
        badge = (
            f' <a class="cite-tag" href="{scix_url(c["bibcode"])}" target="_blank" rel="noopener" '
            f'title="SciX citations · updated {c["fetched"]}">{c["n"]} {word}</a>'
        )
        head = re.sub(
            r'(<div class="paper-item[^"]*" id="p\d+")', rf'\1 data-cites="{c["n"]}"', head, count=1
        )
        report = report[: m.start()] + head.rstrip() + badge + m.group(2) + report[m.end() :]
    return report
