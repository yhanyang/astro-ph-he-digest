"""Build the static GitHub Pages site from the reports directory.

Writes into ``reports/``:

* ``index.html`` -- header (arXiv · astro-ph.HE · team) with tabs:
  **Day** (latest listing by default, ‹ › and a day picker), **Week** (week summary, ‹ › and a
  week picker) and **Month** (month summary, ‹ › and a month picker) and **Year** (year summary). Everything is addressable
  by hash: ``#today``, ``#day/<date>[/pN]``, ``#week/<ISO week>[/<date>[/pN]]``,
  ``#month/<YYYY-MM>[/<ISO week>]``; ``#<date>[/pN]`` keeps working.
* ``week-<ISO week>.html`` / ``month-<YYYY-MM>.html`` -- summaries: highlights,
  topic statistics and per-topic paper lists whose links deep-link into the
  daily reports. ``week.html`` and ``month.html`` alias the latest ones.
* ``latest.html`` -- redirects to the newest daily report.
"""

import datetime
import glob
import html
import json
import os
import re
import shutil

from core.config import SITE_TEAM
from core.render import FRAGMENTS_DIR, REPORTS_DIR, STARRED_REPORT
from core.topics import (
    CHIP_CSS,
    FOCUS_LABELS,
    GRB_LABEL,
    OTHER_GROUP,
    OTHER_LABEL,
    TOPICS,
    topic_abbr,
    topic_class,
)
from core.wiki import clean_title, parse_fragment

REPORT_RE = re.compile(r'^arXiv_astro_ph_HE_daily_report_(\d{4}-\d{2}-\d{2})\.html$')
SITE_TITLE = os.getenv('SITE_TITLE', 'arXiv · astro-ph.HE')
_ORDER = {label: i for i, (label, _) in enumerate(TOPICS)}


def report_file(date_str: str) -> str:
    return f'arXiv_astro_ph_HE_daily_report_{date_str}.html'


def _report_dates() -> list[str]:
    if not os.path.isdir(REPORTS_DIR):
        return []
    dates = [m.group(1) for f in os.listdir(REPORTS_DIR) if (m := REPORT_RE.match(f))]
    return sorted(dates, reverse=True)


def _read(path: str) -> str:
    with open(path, encoding='utf-8-sig') as f:
        return f.read()


def _fragment(date_str: str) -> str | None:
    path = os.path.join(FRAGMENTS_DIR, f'{date_str}.html')
    return _read(path) if os.path.exists(path) else None


_DISMISSED: set[str] | None = None


def _dismissed() -> set[str]:
    global _DISMISSED
    if _DISMISSED is None:
        from core import feedback

        _DISMISSED = feedback.dismissed()
    return _DISMISSED


_CITES: dict[str, dict] | None = None


def _citations() -> dict[str, dict]:
    global _CITES
    if _CITES is None:
        try:
            from core import citations

            _CITES = citations.all_counts()
        except Exception:
            _CITES = {}
    return _CITES


def _pid(entry: dict) -> str:
    from core.corpus import arxiv_pid

    return arxiv_pid('http://arxiv.org/abs/' + entry.get('arxiv_id', '')) or ''


def _parsed(date_str: str) -> dict:
    """Parsed fragment with 👎-dismissed papers demoted: no highlight, not a focus paper."""
    text = _fragment(date_str) or _read(os.path.join(REPORTS_DIR, report_file(date_str)))
    pf = parse_fragment(text)
    if _dismissed():
        from core.corpus import arxiv_pid

        for n, entry in pf['papers'].items():
            if arxiv_pid('http://arxiv.org/abs/' + entry.get('arxiv_id', '')) in _dismissed():
                pf['highlights'].pop(n, None)
                pf['topics'][n] = [t for t in pf['topics'].get(n, []) if t not in FOCUS_LABELS] or [
                    OTHER_LABEL
                ]
                entry['dismissed'] = True
    return pf


def _label(date_str: str, fmt: str = '%a, %d %b') -> str:
    return datetime.date.fromisoformat(date_str).strftime(fmt)


def _iso_week(date_str: str) -> str:
    y, w, _ = datetime.date.fromisoformat(date_str).isocalendar()
    return f'{y}-W{w:02d}'


def _week_span(key: str) -> tuple[datetime.date, datetime.date]:
    y, w = key.split('-W')
    monday = datetime.date.fromisocalendar(int(y), int(w), 1)
    return monday, monday + datetime.timedelta(days=6)


def _week_label(key: str) -> str:
    mon, sun = _week_span(key)
    return f'{mon:%d %b} – {sun:%d %b %Y}'


def _month_label(key: str) -> str:
    y, m = key.split('-')
    return datetime.date(int(y), int(m), 1).strftime('%B %Y')


def _short_authors(authors: str, n: int = 3) -> str:
    parts = [a.strip() for a in authors.split(',') if a.strip()]
    return ', '.join(parts[:n]) + (' et al.' if len(parts) > n else '')


def _chip(label: str, count: int | None = None, small: bool = False) -> str:
    n = f'<span class="chip-n">{count}</span>' if count is not None else ''
    cls = 'chip chip-sm' if small else 'chip'
    return (
        f'<span class="{cls} {topic_class(label)}" title="{html.escape(label)}">'
        f'<span class="chip-abbr">{html.escape(topic_abbr(label))}</span>{n}</span>'
    )


def _day_link(date: str, number: int | None, text: str) -> str:
    """Link to one paper (or the day); the page script retargets it to the index or the web UI."""
    anchor = f'p{number}' if number else ''
    return (
        f'<a class="dl" data-date="{date}" data-anchor="{anchor}" '
        f'href="{report_file(date)}{"#" + anchor if anchor else ""}">{text}</a>'
    )


def _month_link(key: str, text: str) -> str:
    return f'<a class="ml" data-month="{key}" href="index.html#month/{key}">{text}</a>'


def _week_link(key: str, text: str) -> str:
    return f'<a class="wl" data-week="{key}" href="index.html#week/{key}">{text}</a>'


_SUMMARY_CSS = """
:root { color-scheme: light dark; --bg:#fbfbfc; --surface:#ffffff; --alt:#f4f6f9; --text:#1f2933; --muted:#6b7280; --primary:#1f4e8c; --border:#e5e7eb; --tag:#e4eef9; --hl:#92400e; --hlbg:#fff7ed; }
@media (prefers-color-scheme: dark) { :root { --bg:#0f172a; --surface:#1e293b; --alt:#172033; --text:#e2e8f0; --muted:#94a3b8; --primary:#93c5fd; --border:#334155; --tag:#1e3a5f; --hl:#fdba74; --hlbg:#2a1f14; } }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--text); font:15px/1.55 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; }
.wrap { max-width:1040px; margin:0 auto; padding:28px 24px 60px; }
header .kicker { margin:0 0 4px; font-size:.72rem; text-transform:uppercase; letter-spacing:.1em; color:var(--muted); font-weight:600; }
header h1 { margin:0 0 4px; font-size:1.5rem; }
header p { margin:0; color:var(--muted); }
.block { margin-top:24px; background:var(--surface); border:1px solid var(--border); border-radius:12px; padding:18px 22px; }
.block h2 { margin:0 0 12px; font-size:1.1rem; display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
.block h2 small { color:var(--muted); font-weight:500; font-size:.8rem; }
a { color:var(--primary); text-decoration:none; } a:hover { text-decoration:underline; }
ul { margin:0; padding-left:20px; } li { margin:6px 0; }
.meta { color:var(--muted); font-size:.85em; }
.hl { list-style:none; padding:0; }
.hl li { margin:10px 0; padding:10px 12px; background:var(--hlbg); border-left:3px solid var(--hl); border-radius:6px; }
.hl-text { display:inline-block; margin-top:4px; }
table.stats { border-collapse:collapse; width:100%; font-size:.92em; }
.stats th, .stats td { padding:6px 8px; border-bottom:1px solid var(--border); text-align:center; }
.stats th[scope=row] { text-align:left; font-weight:500; }
.stats th[scope=row] .chip { margin-right:8px; vertical-align:middle; }
.stats thead th { color:var(--muted); font-weight:600; }
.stats .tot { font-weight:700; }
.stats tr.nf { color:var(--muted); } .stats tr.nf .tot { font-weight:500; }
.stats tr.sep th { text-align:left; color:var(--muted); font-size:.72rem; text-transform:uppercase; letter-spacing:.08em; padding-top:12px; border-bottom:0; }
.tag { display:inline-block; font-size:.72em; padding:0 6px; border-radius:6px; background:var(--tag); color:var(--primary); margin-left:4px; vertical-align:1px; }
.tag.st { background:var(--alt); color:var(--muted); }
ol.cited { margin:0; padding-left:0; list-style:none; }
ol.cited li { padding:5px 0; border-bottom:1px solid var(--border); }
ol.cited li:last-child { border-bottom:0; }
a.cite { display:inline-block; min-width:2.6em; text-align:center; margin-right:6px; padding:0 8px; border-radius:999px; font-size:.78em; font-weight:700; color:#92400e; background:rgba(245,158,11,.18); text-decoration:none; }
a.cite:hover { background:rgba(245,158,11,.32); }
details summary { cursor:pointer; color:var(--muted); }
details ul { margin-top:8px; }
.legend { display:flex; flex-wrap:wrap; gap:7px; margin-top:12px; }
"""

_RETARGET_JS = """
// Paper links: inside the tabbed static index -> index.html#day/<date>/<anchor>;
// inside the FastAPI web UI -> /r/<date>#<anchor>. Standalone: plain file links.
(function () {
  var path = window.location.pathname;
  var inServer = path.indexOf('/r/') !== -1 || path.indexOf('/s/') === 0 || path.indexOf('/week') === 0;
  var inIndex = false;
  try { inIndex = !inServer && window.top !== window && /index\\.html$|\\/$/.test(window.top.location.pathname); } catch (_e) {}
  document.querySelectorAll('a.dl').forEach(function (a) {
    var d = a.dataset.date, p = a.dataset.anchor;
    if (inServer) { a.href = '/r/' + d + (p ? '#' + p : ''); a.target = '_top'; }
    else if (inIndex) { a.href = 'index.html#day/' + d + (p ? '/' + p : ''); a.target = '_top'; }
  });
  document.querySelectorAll('a.wl').forEach(function (a) {
    var w = a.dataset.week;
    if (inServer) { a.href = '/s/week-' + w; a.target = '_top'; }
    else if (inIndex) { a.href = 'index.html#week/' + w; a.target = '_top'; }
  });
  document.querySelectorAll('a.ml').forEach(function (a) {
    var m = a.dataset.month;
    if (inServer) { a.href = '/s/month-' + m; a.target = '_top'; }
    else if (inIndex) { a.href = 'index.html#month/' + m; a.target = '_top'; }
  });
})();
"""


def _summary_page(kind: str, key: str, dates: list[str]) -> str:
    """Week or month summary. ``dates`` ascending, all with reports."""
    parsed = {d: _parsed(d) for d in dates}
    if kind == 'week':
        columns = [(d, _label(d, '%a %d'), _day_link(d, None, _label(d, '%a %d'))) for d in dates]
        col_of = {d: d for d in dates}
        heading, span, kicker = 'This Week in High-Energy Astrophysics', _week_label(key), key
    elif kind == 'month':
        weeks = sorted({_iso_week(d) for d in dates})
        columns = [(w, w.split('-')[1], _week_link(w, w.split('-')[1])) for w in weeks]
        col_of = {d: _iso_week(d) for d in dates}
        heading, span, kicker = 'This Month in High-Energy Astrophysics', _month_label(key), key
    else:  # year
        months = sorted({d[:7] for d in dates})
        columns = [
            (m, _label(m + '-01', '%b'), _month_link(m, _label(m + '-01', '%b'))) for m in months
        ]
        col_of = {d: d[:7] for d in dates}
        heading, span, kicker = 'This Year in High-Energy Astrophysics', key, key

    counts: dict[str, dict[str, int]] = {}
    by_topic: dict[str, list[tuple[str, int, dict]]] = {}
    highlights: list[tuple[str, int, dict, str]] = []
    total = 0
    focus_total = 0
    for d in dates:
        frag = parsed[d]
        total += len(frag['papers'])
        for n, entry in sorted(frag['papers'].items()):
            if any(t in FOCUS_LABELS for t in frag['topics'].get(n, [])):
                focus_total += 1
            for t in frag['topics'].get(n) or [OTHER_LABEL]:
                counts.setdefault(t, {})
                counts[t][col_of[d]] = counts[t].get(col_of[d], 0) + 1
                by_topic.setdefault(t, []).append((d, n, entry))
            if n in frag['highlights']:
                highlights.append((d, n, entry, frag['highlights'][n]))
    labels = sorted(counts, key=lambda x: (_ORDER.get(x, 99), x))

    def title_of(entry: dict) -> str:
        return html.escape(
            clean_title(entry['fields'].get('Title', entry.get('arxiv_id', ''))), quote=False
        )

    # highlights
    hl_items = []
    for d, n, entry, text in highlights:
        topics = parsed[d]['topics'].get(n) or []
        chips = ' '.join(_chip(t, small=True) for t in topics)
        hl_items.append(
            f'<li>{_day_link(d, n, f"<strong>{title_of(entry)}</strong>")} {chips} '
            f'<span class="meta">{_label(d)} · [{n}]</span><br><span class="hl-text">{text}</span></li>'
        )
    if kind == 'year' and hl_items:
        by_month: dict[str, list[str]] = {}
        for (d, _n, _e, _t), item in zip(highlights, hl_items, strict=True):
            by_month.setdefault(d[:7], []).append(item)
        groups = ''.join(
            f'<details><summary>{_month_label(mo)} — {len(items)} highlights</summary>'
            f'<ul class="hl">{"".join(items)}</ul></details>'
            for mo, items in sorted(by_month.items(), reverse=True)
        )
        hl_html = f'<section class="block"><h2>Highlights <small>{len(hl_items)}</small></h2>{groups}</section>'
    else:
        hl_html = (
            f'<section class="block"><h2>Highlights <small>{len(hl_items)}</small></h2>'
            f'<ul class="hl">{"".join(hl_items)}</ul></section>'
            if hl_items
            else ''
        )

    # most cited (SciX)
    cites = _citations()
    cited: list[tuple[int, str, int, dict, dict]] = []
    for d in dates:
        for n, entry in parsed[d]['papers'].items():
            c = cites.get(_pid(entry))
            if c and c['n'] > 0:
                cited.append((c['n'], d, n, entry, c))
    cited.sort(key=lambda x: (-x[0], x[1], x[2]))
    limit = {'week': 10, 'month': 15}.get(kind, 25)
    cite_html = ''
    if cited:
        from core.citations import scix_url

        items = []
        for ncit, d, n, entry, c in cited[:limit]:
            topics = parsed[d]['topics'].get(n) or []
            chips = ' '.join(_chip(tp, small=True) for tp in topics)
            ref = ' · refereed' if c.get('refereed') else ''
            items.append(
                f'<li><a class="cite" href="{scix_url(c["bibcode"])}" target="_blank" rel="noopener" '
                f'title="SciX · updated {c["fetched"]}">{ncit}</a> {_day_link(d, n, title_of(entry))} {chips} '
                f'<span class="meta">{_label(d)} · [{n}]{ref}</span></li>'
            )
        updated = max(c['fetched'] for _, _, _, _, c in cited)
        cite_html = (
            f'<section class="block"><h2>Most cited <small>SciX · {len(cited)} papers cited · updated {updated}</small></h2>'
            f'<ol class="cited">{"".join(items)}</ol></section>'
        )

    # statistics
    head = ''.join(f'<th>{link}</th>' for _, _, link in columns)
    rows = []
    for label in labels:
        per = counts[label]
        tot = sum(per.values())
        cells = ''.join(f'<td>{per.get(c, "") or "·"}</td>' for c, _, _ in columns)
        anchor = re.sub(r'[^A-Za-z0-9]+', '-', label).strip('-').lower()
        if label not in FOCUS_LABELS and not any('class="sep"' in r for r in rows):
            rows.append(
                f'<tr class="sep"><th colspan="{len(columns) + 2}">{OTHER_GROUP} · index only</th></tr>'
            )
        rows.append(
            f'<tr{"" if label in FOCUS_LABELS else " class=nf"}><th scope="row">{_chip(label, small=True)}<a href="#t-{anchor}">'
            f'{html.escape(label, quote=False)}</a></th>{cells}<td class="tot">{tot}</td></tr>'
        )
    stats_html = (
        f'<section class="block"><h2>Topic statistics <small>★ {focus_total} / {total} papers</small></h2>'
        f'<table class="stats"><thead><tr><th>Topic</th>{head}<th>Total</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table></section>'
    )

    # per-topic lists
    sections = []
    for label in labels:
        items = by_topic[label]
        anchor = re.sub(r'[^A-Za-z0-9]+', '-', label).strip('-').lower()
        lis = []
        for d, n, entry in sorted(items, key=lambda x: (x[0], x[1]), reverse=True):
            method = (
                f' <span class="tag">{html.escape(entry["method"])}</span>'
                if entry.get('method')
                else ''
            )
            status = (
                f' <span class="tag st">{html.escape(entry["status"])}</span>'
                if entry.get('status')
                else ''
            )
            if entry.get('dismissed'):
                status += ' <span class="tag st">👎 dismissed</span>'
            lis.append(
                f'<li>{_day_link(d, n, title_of(entry))} <span class="meta">{_label(d)} · [{n}] · '
                f'{html.escape(_short_authors(entry["fields"].get("Authors", "")), quote=False)}</span>'
                f'{method}{status}</li>'
            )
        body = f'<ul class="papers">{"".join(lis)}</ul>'
        if label not in FOCUS_LABELS or kind in ('month', 'year'):
            note = 'index only' if label not in FOCUS_LABELS else 'titles'
            body = f'<details><summary>{len(items)} papers, {note} — click to expand</summary>{body}</details>'
        sections.append(
            f'<section class="block topic" id="t-{anchor}"><h2>{_chip(label)}'
            f'{html.escape(label, quote=False)} <small>{len(items)}</small></h2>{body}</section>'
        )

    legend = ''.join(_chip(label, sum(counts[label].values()), small=True) for label in labels)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>arXiv · astro-ph.HE · {kicker}{'' if span == kicker else f' ({span})'}</title>
<style>{_SUMMARY_CSS}{CHIP_CSS}</style>
</head>
<body>
<div class="wrap">
<header>
  <p class="kicker">arXiv · astro-ph.HE{' · ' + html.escape(SITE_TEAM) if SITE_TEAM else ''} · {kicker}</p>
  <h1>{heading}</h1>
  <p>{span} · <span title="papers in focus topics / all papers">★ {focus_total} / {total} papers</span> over {len(dates)} listing day{'' if len(dates) == 1 else 's'} · every paper links to its entry in the daily report</p>
  <div class="legend">{legend}</div>
</header>
{hl_html}
{cite_html}
{stats_html}
{''.join(sections)}
</div>
<script>{_RETARGET_JS}</script>
</body>
</html>
"""


_INDEX_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>__TITLE__</title>
<style>
:root { color-scheme: light dark; --bg:#f8f9fb; --surface:#fff; --border:#e2e6ea; --text:#1a202c; --muted:#6b7280; --primary:#1e3a8a; --grb:#c2410c; }
@media (prefers-color-scheme: dark) { :root { --bg:#0f172a; --surface:#1e293b; --border:#334155; --text:#f1f5f9; --muted:#94a3b8; --primary:#60a5fa; --grb:#fb923c; } }
* { box-sizing:border-box; margin:0; padding:0; }
html, body { height:100%; }
body { display:flex; flex-direction:column; background:var(--bg); color:var(--text); font:15px/1.5 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; }
header { background:linear-gradient(135deg,#0f2167 0%,#1e3a8a 50%,#2563eb 100%); color:#fff; padding:18px 24px 0; }
.top { display:flex; justify-content:space-between; align-items:flex-start; gap:12px; flex-wrap:wrap; }
h1 { font-size:1.35rem; font-weight:700; } h1 span.dot { opacity:.6; font-weight:400; }
.team { display:inline-block; margin-left:10px; padding:2px 10px; border-radius:999px; background:rgba(255,255,255,.16); font-size:.72rem; font-weight:600; letter-spacing:.04em; vertical-align:middle; }
.header-meta { font-size:.78rem; opacity:.78; margin-top:3px; }
.links { display:flex; gap:14px; padding-top:5px; font-size:.82rem; } .links a { color:#fff; opacity:.85; text-decoration:none; } .links a:hover { opacity:1; text-decoration:underline; }
nav.tabs { display:flex; gap:4px; margin-top:14px; overflow-x:auto; scrollbar-width:thin; }
.tab { flex:none; border:0; background:rgba(255,255,255,.1); color:rgba(255,255,255,.85); padding:8px 16px 9px; border-radius:10px 10px 0 0; cursor:pointer; font:inherit; font-size:.84rem; line-height:1.3; text-align:left; min-width:150px; }
.tab:hover { background:rgba(255,255,255,.2); } .tab small { display:block; font-size:.7rem; opacity:.75; }
.tab.active { background:var(--bg); color:var(--text); } .tab.active small { opacity:.7; }
.subbar { display:flex; align-items:center; gap:12px; flex-wrap:wrap; padding:9px 24px; border-bottom:1px solid var(--border); background:var(--bg); min-height:48px; }
.nav { display:flex; align-items:center; gap:6px; font-size:.88rem; font-weight:600; }
.nav > button, .nav > select { border:1px solid var(--border); background:var(--surface); color:var(--text); border-radius:8px; height:28px; cursor:pointer; font:inherit; }
.nav > button { width:28px; } .nav > select { padding:0 6px; font-size:.82rem; max-width:220px; }
.nav > button:disabled { opacity:.3; cursor:default; }
.nav .range { color:var(--muted); font-weight:500; margin-left:4px; }
.pick { display:flex; gap:6px; flex-wrap:wrap; }
.pick button { border:1px solid var(--border); background:var(--surface); color:var(--muted); border-radius:20px; padding:4px 12px; cursor:pointer; font:inherit; font-size:.8rem; font-weight:500; display:inline-flex; align-items:center; gap:6px; }
.pick button:hover { border-color:var(--primary); color:var(--primary); }
.pick button.active { background:var(--primary); border-color:var(--primary); color:#fff; }
.pick button .n { font-size:.7rem; opacity:.75; } .pick button.active .n { opacity:.9; }
.pick .grb, .nav .grb { display:inline-block; padding:0 6px; border-radius:8px; background:var(--grb); color:#fff; font-size:.64rem; font-weight:700; }
.open { margin-left:auto; font-size:.78rem; color:var(--muted); text-decoration:none; white-space:nowrap; } .open:hover { color:var(--primary); }
.cal { position:relative; }
.cal-btn { border:1px solid var(--border); background:var(--surface); color:var(--text); border-radius:8px; height:28px; padding:0 10px; cursor:pointer; font:inherit; font-size:.8rem; font-weight:500; }
.cal-btn:hover { border-color:var(--primary); color:var(--primary); }
.cal-pop { position:absolute; top:34px; left:0; z-index:50; background:var(--surface); border:1px solid var(--border); border-radius:12px; box-shadow:0 10px 28px rgba(0,0,0,.18); padding:10px 12px 12px; }
.cal-head { display:flex; align-items:center; justify-content:space-between; gap:8px; font-weight:600; font-size:.88rem; margin-bottom:8px; }
.cal-head button { border:1px solid var(--border); background:var(--surface); color:var(--text); border-radius:8px; width:26px; height:26px; cursor:pointer; font:inherit; }
.cal-head button:disabled { opacity:.3; cursor:default; }
.cal-grid { display:grid; grid-template-columns:36px repeat(7, 34px); gap:3px; font-size:.78rem; }
.cal-grid .wd { color:var(--muted); text-align:center; font-size:.66rem; font-weight:600; padding-bottom:2px; }
.cal-grid .d, .cal-grid .wk { height:30px; display:flex; align-items:center; justify-content:center; border-radius:7px; color:var(--muted); border:1px solid transparent; font:inherit; font-size:.78rem; }
.cal-grid .d.out { opacity:.35; }
.cal-grid button.d { background:var(--surface); border-color:var(--border); color:var(--text); cursor:pointer; font-weight:600; }
.cal-grid button.d:hover, .cal-grid button.wk:hover { border-color:var(--primary); color:var(--primary); }
.cal-grid .wk { font-size:.68rem; } .cal-grid button.wk { background:var(--surface); border-color:var(--border); color:var(--primary); cursor:pointer; font-weight:700; }
.cal-grid .sel, .cal-months .sel { background:var(--primary) !important; color:#fff !important; border-color:var(--primary) !important; }
.cal-months { display:grid; grid-template-columns:repeat(3, 1fr); gap:6px; min-width:250px; }
.cal-months .cm { padding:8px 6px; border-radius:8px; border:1px solid transparent; text-align:center; color:var(--muted); font-size:.8rem; display:flex; flex-direction:column; gap:2px; align-items:center; font:inherit; }
.cal-months button.cm { background:var(--surface); border-color:var(--border); color:var(--text); cursor:pointer; font-weight:600; }
.cal-months button.cm:hover { border-color:var(--primary); color:var(--primary); }
.cal-months .cm .n { font-size:.66rem; opacity:.7; font-weight:500; }
iframe { flex:1; width:100%; border:0; background:var(--bg); }
.fallback, .empty { padding:28px 24px; color:var(--muted); line-height:1.6; }
.fallback a { color:var(--primary); }
@media (max-width:600px) { header { padding:14px 16px 0; } .subbar { padding:8px 16px; } .tab { min-width:0; } .open { display:none; } }
</style>
</head>
<body>
<header>
  <div class="top">
    <div>
      <h1>arXiv <span class="dot">·</span> astro-ph.HE __TEAM_SPAN__</h1>
      <div class="header-meta" id="header-meta">__META__</div>
    </div>
    <div class="links" id="links"><a href="wiki/Home.html" target="_top">📚 Wiki</a><a href="__STARRED__" target="_top">★ My starred papers</a></div>
  </div>
  <nav class="tabs" id="tabs" role="tablist" aria-label="Views">
    <button class="tab" data-tab="day" role="tab">Day<small id="sub-day"></small></button>
    <button class="tab" data-tab="week" role="tab">Week<small id="sub-week"></small></button>
    <button class="tab" data-tab="month" role="tab">Month<small id="sub-month"></small></button>
    <button class="tab" data-tab="year" role="tab">Year<small id="sub-year"></small></button>
  </nav>
</header>
<div class="subbar" id="subbar"></div>
<iframe id="view" title="Report"></iframe>
<div class="fallback" id="fallback" hidden></div>
<p class="empty" id="empty" hidden>No reports yet. The first one appears after the next scheduled run.</p>
<script id="site-data" type="application/json">__DATA__</script>
<script>
const DATA = JSON.parse(document.getElementById('site-data').textContent);
const view = document.getElementById('view'), subbar = document.getElementById('subbar'), fallback = document.getElementById('fallback');
const DATE_RE = /^\\d{4}-\\d{2}-\\d{2}$/;
const DAY_ORDER = Object.keys(DATA.days).sort().reverse();   // newest first
const latestDay = DATA.latest;
const latestWeek = latestDay ? DATA.days[latestDay].week : null;
const latestMonth = latestDay ? DATA.days[latestDay].month : null;
const latestYear = latestDay ? latestDay.slice(0, 4) : null;
// Served by the FastAPI web UI (at /site/): load reports through the server routes so that the
// promote / like / dislike / similar buttons work; otherwise plain static files (GitHub Pages).
const SERVER = location.pathname.indexOf('/site/') === 0;
function daySrc(d) { return SERVER ? '/r/' + d + '/raw' : DATA.days[d].src; }
function sumSrc(kind, key, obj) { return SERVER ? '/s/' + kind + '-' + key + '/raw' : obj.src; }
if (SERVER) {
  const links = document.getElementById('links');
  links.innerHTML = '';
  [['📚 Wiki', '/wiki/Home.html'], ['🔍 Search', '/search'], ['✦ Recommend', '/recommend'], ['★ Starred', '/starred'], ['👍 Liked', '/liked']].forEach(function (x) {
    const a = document.createElement('a'); a.textContent = x[0]; a.href = x[1]; a.target = '_top'; links.appendChild(a);
  });
}

function cnt(o) { return '★ ' + o.focus + ' / ' + o.n + ' papers'; }   // focus-topic papers / all papers
function el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; }
function dayRoute(date, anchor) {
  return DATA.days[date] ? {tab: 'day', key: date, anchor: anchor || ''} : {tab: 'day', key: latestDay, anchor: ''};
}
function parseHash() {
  const raw = decodeURIComponent(location.hash.slice(1));
  const p = raw.split('/');
  if (!raw || p[0] === 'today' || (p[0] === 'day' && !p[1])) return dayRoute(latestDay);
  if (DATE_RE.test(p[0])) return dayRoute(p[0], p[1]);          // legacy #<date>[/pN]
  if (p[0] === 'day') return dayRoute(p[1], p[2]);
  if (p[0] === 'week') {
    if (DATA.days[p[2]]) return dayRoute(p[2], p[3]);          // week/<key>/<date> -> that day
    return {tab: 'week', key: DATA.weeks[p[1]] ? p[1] : latestWeek};
  }
  if (p[0] === 'month') {
    if (DATA.weeks[p[2]]) return {tab: 'week', key: p[2]};      // month/<key>/<week> -> that week
    return {tab: 'month', key: DATA.months[p[1]] ? p[1] : latestMonth};
  }
  if (p[0] === 'year') return {tab: 'year', key: DATA.years[p[1]] ? p[1] : latestYear};
  return dayRoute(latestDay);
}
function pickButton(label, sub, active, hash, grb) {
  const b = el('button', active ? 'active' : '');
  b.appendChild(document.createTextNode(label));
  if (sub) b.appendChild(el('span', 'n', sub));
  if (grb) b.appendChild(el('span', 'grb', 'GRB ' + grb));
  b.onclick = function () { location.hash = hash; };
  return b;
}
function navBlock(title, range, prevKey, nextKey, prefix, grb) {
  const nav = el('div', 'nav');
  const prev = el('button', '', '‹'); prev.title = 'Older'; prev.disabled = !prevKey; prev.onclick = function () { if (prevKey) location.hash = prefix + prevKey; };
  const next = el('button', '', '›'); next.title = 'Newer'; next.disabled = !nextKey; next.onclick = function () { if (nextKey) location.hash = prefix + nextKey; };
  nav.appendChild(prev); nav.appendChild(el('span', '', title));
  if (range) { const rg = el('span', 'range', '· ' + range); rg.title = '★ = papers in focus topics'; nav.appendChild(rg); }
  if (grb) nav.appendChild(el('span', 'grb', 'GRB ' + grb));
  nav.appendChild(next);
  return nav;
}
const MONTHS = ['January','February','March','April','May','June','July','August','September','October','November','December'];
const WD = ['Mo','Tu','We','Th','Fr','Sa','Su'];
function pad(n) { return String(n).padStart(2, '0'); }
function isoDate(d) { return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()); }
function isoWeek(d) {
  const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  const dayNum = t.getUTCDay() || 7;
  t.setUTCDate(t.getUTCDate() + 4 - dayNum);
  const yearStart = new Date(Date.UTC(t.getUTCFullYear(), 0, 1));
  return t.getUTCFullYear() + '-W' + pad(Math.ceil((((t - yearStart) / 86400000) + 1) / 7));
}
const minDay = DAY_ORDER[DAY_ORDER.length - 1], maxDay = DAY_ORDER[0];
// Calendar dropdown shared by the three tabs: pick a day, a week (row) or a month.
function calendar(mode, selected) {
  const wrap = el('div', 'cal');
  const btn = el('button', 'cal-btn', mode === 'day' ? '📅 Pick a day ▾' : mode === 'week' ? '📅 Pick a week ▾' : '📅 Pick a month ▾');
  const pop = el('div', 'cal-pop'); pop.hidden = true;
  let y, m;
  if (mode === 'year') {
    btn.textContent = '📅 Pick a year ▾';
    function drawYears() {
      pop.innerHTML = '';
      const grid = el('div', 'cal-months');
      DATA.yearOrder.forEach(function (k) {
        const c = el('button', 'cm' + (k === selected ? ' sel' : ''), k);
        c.appendChild(el('span', 'n', cnt(DATA.years[k])));
        c.onclick = function () { location.hash = 'year/' + k; };
        grid.appendChild(c);
      });
      pop.appendChild(grid);
    }
    btn.onclick = function (e) { e.stopPropagation(); const open = pop.hidden; document.querySelectorAll('.cal-pop').forEach(function (p) { p.hidden = true; }); if (open) { drawYears(); pop.hidden = false; } };
    pop.onclick = function (e) { e.stopPropagation(); };
    wrap.appendChild(btn); wrap.appendChild(pop);
    return wrap;
  }
  if (mode === 'month') { y = parseInt((selected || latestMonth).slice(0, 4), 10); }
  else {
    const base = mode === 'day' ? selected : (DATA.weeks[selected] ? DATA.weeks[selected].days[0] : latestDay);
    y = parseInt(base.slice(0, 4), 10); m = parseInt(base.slice(5, 7), 10) - 1;
  }
  const minYM = parseInt(minDay.slice(0, 4), 10) * 12 + parseInt(minDay.slice(5, 7), 10) - 1;
  const maxYM = parseInt(maxDay.slice(0, 4), 10) * 12 + parseInt(maxDay.slice(5, 7), 10) - 1;
  function draw() {
    pop.innerHTML = '';
    const head = el('div', 'cal-head');
    const prev = el('button', '', '‹'), next = el('button', '', '›');
    if (mode === 'month') {
      head.appendChild(prev); head.appendChild(el('span', '', String(y))); head.appendChild(next);
      prev.disabled = y <= parseInt(minDay.slice(0, 4), 10); next.disabled = y >= parseInt(maxDay.slice(0, 4), 10);
      prev.onclick = function (e) { e.stopPropagation(); y -= 1; draw(); };
      next.onclick = function (e) { e.stopPropagation(); y += 1; draw(); };
      pop.appendChild(head);
      const grid = el('div', 'cal-months');
      for (let i = 0; i < 12; i++) {
        const key = y + '-' + pad(i + 1), info = DATA.months[key];
        const c = el(info ? 'button' : 'span', 'cm' + (key === selected ? ' sel' : ''), MONTHS[i].slice(0, 3));
        if (info) { c.appendChild(el('span', 'n', cnt(info))); c.onclick = function () { location.hash = 'month/' + key; }; }
        grid.appendChild(c);
      }
      pop.appendChild(grid);
      return;
    }
    head.appendChild(prev); head.appendChild(el('span', '', MONTHS[m] + ' ' + y)); head.appendChild(next);
    prev.disabled = (y * 12 + m) <= minYM; next.disabled = (y * 12 + m) >= maxYM;
    prev.onclick = function (e) { e.stopPropagation(); if (m === 0) { m = 11; y -= 1; } else { m -= 1; } draw(); };
    next.onclick = function (e) { e.stopPropagation(); if (m === 11) { m = 0; y += 1; } else { m += 1; } draw(); };
    pop.appendChild(head);
    const grid = el('div', 'cal-grid');
    grid.appendChild(el('span', 'wd', ''));
    WD.forEach(function (w) { grid.appendChild(el('span', 'wd', w)); });
    const first = new Date(y, m, 1), last = new Date(y, m + 1, 0);
    const start = new Date(first); start.setDate(first.getDate() - ((first.getDay() + 6) % 7));
    for (let row = 0; row < 6; row++) {
      const monday = new Date(start); monday.setDate(start.getDate() + row * 7);
      if (monday > last) break;
      const wkey = isoWeek(monday), wInfo = DATA.weeks[wkey];
      const clickable = wInfo && mode === 'week';
      const wl = el(clickable ? 'button' : 'span', 'wk' + (wkey === selected ? ' sel' : ''), wkey.split('-')[1]);
      if (clickable) { wl.title = cnt(wInfo); wl.onclick = function () { location.hash = 'week/' + wkey; }; }
      grid.appendChild(wl);
      for (let i = 0; i < 7; i++) {
        const d = new Date(monday); d.setDate(monday.getDate() + i);
        const k = isoDate(d), info = DATA.days[k], out = d.getMonth() !== m ? ' out' : '';
        if (info) {
          const b = el('button', 'd' + out + (k === selected ? ' sel' : ''), String(d.getDate()));
          b.title = cnt(info) + (info.grb ? ' · GRB ' + info.grb : '');
          b.onclick = function () { location.hash = 'day/' + k; };
          grid.appendChild(b);
        } else {
          grid.appendChild(el('span', 'd' + out, String(d.getDate())));
        }
      }
    }
    pop.appendChild(grid);
  }
  btn.onclick = function (e) {
    e.stopPropagation();
    const open = pop.hidden;
    document.querySelectorAll('.cal-pop').forEach(function (p) { p.hidden = true; });
    if (open) { draw(); pop.hidden = false; }
  };
  pop.onclick = function (e) { e.stopPropagation(); };
  wrap.appendChild(btn); wrap.appendChild(pop);
  return wrap;
}
document.addEventListener('click', function () { document.querySelectorAll('.cal-pop').forEach(function (p) { p.hidden = true; }); });
let loadTimer = null;
function showSrc(src, anchor) {
  const full = src + (anchor ? '#' + anchor : '');
  const open = el('a', 'open', 'open standalone ↗'); open.href = full; open.target = '_blank'; open.rel = 'noopener';
  subbar.appendChild(open);
  fallback.hidden = true;
  if (view.getAttribute('src') !== full) {
    clearTimeout(loadTimer);
    let loaded = false;
    view.onload = function () { loaded = true; fallback.hidden = true; };
    view.setAttribute('src', full);
    loadTimer = setTimeout(function () {
      if (loaded) return;
      fallback.innerHTML = '';
      fallback.appendChild(document.createTextNode('The embedded view did not load (the host may block frames). '));
      const a = el('a', '', 'Open ' + src + ' directly'); a.href = full; a.target = '_blank'; a.rel = 'noopener';
      fallback.appendChild(a); fallback.hidden = false;
    }, 6000);
  }
}
function render() {
  if (!latestDay) { view.hidden = true; document.getElementById('empty').hidden = false; return; }
  const r = parseHash();
  document.querySelectorAll('.tab').forEach(function (b) { const on = b.dataset.tab === r.tab; b.classList.toggle('active', on); b.setAttribute('aria-selected', on); });
  subbar.innerHTML = '';
  let src = '', anchor = '';
  if (r.tab === 'day') {
    const d = DATA.days[r.key], i = DAY_ORDER.indexOf(r.key);
    subbar.appendChild(navBlock(d.long, cnt(d), DAY_ORDER[i + 1], DAY_ORDER[i - 1], 'day/', d.grb));
    subbar.querySelector('.nav').appendChild(calendar('day', r.key));
    src = daySrc(r.key); anchor = r.anchor;
  } else if (r.tab === 'week') {
    const w = DATA.weeks[r.key], i = DATA.weekOrder.indexOf(r.key);
    subbar.appendChild(navBlock(r.key.split('-')[1], w.span + ' · ' + cnt(w), DATA.weekOrder[i + 1], DATA.weekOrder[i - 1], 'week/'));
    subbar.querySelector('.nav').appendChild(calendar('week', r.key));
    src = sumSrc('week', r.key, w);
  } else if (r.tab === 'year') {
    const yv = DATA.years[r.key], i = DATA.yearOrder.indexOf(r.key);
    subbar.appendChild(navBlock(r.key, cnt(yv) + ' · ' + yv.months.length + ' months', DATA.yearOrder[i + 1], DATA.yearOrder[i - 1], 'year/'));
    subbar.querySelector('.nav').appendChild(calendar('year', r.key));
    src = sumSrc('year', r.key, yv);
  } else {
    const m = DATA.months[r.key], i = DATA.monthOrder.indexOf(r.key);
    subbar.appendChild(navBlock(m.label, cnt(m), DATA.monthOrder[i + 1], DATA.monthOrder[i - 1], 'month/'));
    subbar.querySelector('.nav').appendChild(calendar('month', r.key));
    src = sumSrc('month', r.key, m);
  }
  showSrc(src, anchor);
  // Tab sub-labels follow what is shown; they fall back to the latest day / week / month otherwise.
  const dk = r.tab === 'day' ? r.key : latestDay, wk = r.tab === 'week' ? r.key : latestWeek, mo = r.tab === 'month' ? r.key : latestMonth;
  document.getElementById('sub-day').textContent = DATA.days[dk].label + ' · ' + cnt(DATA.days[dk]);
  document.getElementById('sub-week').textContent = wk.split('-')[1] + ' · ' + DATA.weeks[wk].span + ' · ' + cnt(DATA.weeks[wk]);
  document.getElementById('sub-month').textContent = DATA.months[mo].label + ' · ' + cnt(DATA.months[mo]);
  const yr = r.tab === 'year' ? r.key : latestYear;
  document.getElementById('sub-year').textContent = yr + ' · ' + cnt(DATA.years[yr]);
}
document.querySelectorAll('.tab').forEach(function (b) { b.onclick = function () { location.hash = b.dataset.tab; }; });
window.addEventListener('hashchange', render);
// A report in the frame reports feedback (like / dismiss / promote): re-read the counts in place.
function refreshCounts() {
  fetch(location.pathname, {cache: 'no-store'}).then(function (r) { return r.text(); }).then(function (html) {
    const doc = new DOMParser().parseFromString(html, 'text/html');
    const node = doc.getElementById('site-data');
    if (!node) return;
    const fresh = JSON.parse(node.textContent);
    Object.keys(fresh).forEach(function (k) { DATA[k] = fresh[k]; });
    const meta = doc.getElementById('header-meta');
    if (meta) document.getElementById('header-meta').textContent = meta.textContent;
    render();   // showSrc() leaves the frame alone while its src is unchanged
  }).catch(function () {});
}
window.addEventListener('message', function (e) {
  if (!e.data || e.data.type !== 'arxiv-report:feedback') return;
  // The server rebuilds the summaries in the background after answering; read twice.
  setTimeout(refreshCounts, 1500);
  setTimeout(refreshCounts, 6000);
});
render();
</script>
</body>
</html>
"""


def _write_atomic(path: str, text: str, encoding: str = 'utf-8-sig') -> None:
    """Write via a temp file + rename so readers never see a partial or missing page."""
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding=encoding) as f:
        f.write(text)
    os.replace(tmp, path)


def build() -> None:
    global _DISMISSED, _CITES
    _DISMISSED = None  # re-read 👎 verdicts on every build (the web UI keeps this module loaded)
    _CITES = None
    dates = _report_dates()  # newest first
    days: dict[str, dict] = {}
    for d in dates:
        pf = _parsed(d)
        grb = sum(1 for n, ts in pf['topics'].items() if GRB_LABEL in ts)
        focus = sum(1 for n, ts in pf['topics'].items() if any(t in FOCUS_LABELS for t in ts))
        days[d] = {
            'n': len(pf['papers']),
            'focus': focus,
            'grb': grb,
            'src': report_file(d),
            'week': _iso_week(d),
            'month': d[:7],
            'label': _label(d, '%a %d %b'),
            'long': _label(d, '%A, %d %B %Y'),
        }
    weeks: dict[str, list[str]] = {}
    months: dict[str, list[str]] = {}
    for d in sorted(days):
        weeks.setdefault(days[d]['week'], []).append(d)
        months.setdefault(days[d]['month'], []).append(d)

    os.makedirs(REPORTS_DIR, exist_ok=True)
    # Write every summary first and only then drop stale ones, so a page that is open in a
    # browser (or auto-reloaded by a live-preview server) never sees a missing file.
    wanted = set()
    for key, ds in weeks.items():
        name = f'week-{key}.html'
        wanted.add(name)
        _write_atomic(os.path.join(REPORTS_DIR, name), _summary_page('week', key, ds))
    for key, ds in months.items():
        name = f'month-{key}.html'
        wanted.add(name)
        _write_atomic(os.path.join(REPORTS_DIR, name), _summary_page('month', key, ds))
    years: dict[str, list[str]] = {}
    for d in sorted(days):
        years.setdefault(d[:4], []).append(d)
    for key, ds in years.items():
        name = f'year-{key}.html'
        wanted.add(name)
        _write_atomic(os.path.join(REPORTS_DIR, name), _summary_page('year', key, ds))
    for stale in (
        glob.glob(os.path.join(REPORTS_DIR, 'week-*.html'))
        + glob.glob(os.path.join(REPORTS_DIR, 'month-*.html'))
        + glob.glob(os.path.join(REPORTS_DIR, 'year-*.html'))
    ):
        if os.path.basename(stale) not in wanted:
            os.remove(stale)
    if dates:
        shutil.copyfile(
            os.path.join(REPORTS_DIR, f'week-{days[dates[0]]["week"]}.html'),
            os.path.join(REPORTS_DIR, 'week.html'),
        )
        shutil.copyfile(
            os.path.join(REPORTS_DIR, f'month-{days[dates[0]]["month"]}.html'),
            os.path.join(REPORTS_DIR, 'month.html'),
        )
        shutil.copyfile(
            os.path.join(REPORTS_DIR, f'year-{dates[0][:4]}.html'),
            os.path.join(REPORTS_DIR, 'year.html'),
        )

    weeks_data = {
        key: {
            'days': ds,
            'n': sum(days[d]['n'] for d in ds),
            'focus': sum(days[d]['focus'] for d in ds),
            'src': f'week-{key}.html',
            'span': _week_label(key),
        }
        for key, ds in weeks.items()
    }
    months_data = {
        key: {
            'weeks': sorted({days[d]['week'] for d in ds}),
            'n': sum(days[d]['n'] for d in ds),
            'focus': sum(days[d]['focus'] for d in ds),
            'src': f'month-{key}.html',
            'label': _month_label(key),
        }
        for key, ds in months.items()
    }
    data = {
        'latest': dates[0] if dates else None,
        'days': days,
        'weeks': weeks_data,
        'months': months_data,
        'years': {
            key: {
                'months': sorted({d[:7] for d in ds}),
                'n': sum(days[d]['n'] for d in ds),
                'focus': sum(days[d]['focus'] for d in ds),
                'src': f'year-{key}.html',
            }
            for key, ds in years.items()
        },
        'yearOrder': sorted(years, reverse=True),
        'weekOrder': sorted(weeks, reverse=True),
        'monthOrder': sorted(months, reverse=True),
    }
    total = sum(v['n'] for v in days.values())
    focus_total = sum(v['focus'] for v in days.values())
    meta = (
        f'{len(days)} listing days · <span title="papers in focus topics / all papers">★ {focus_total} / {total} papers</span>'
        f' · latest {dates[0]}'
        if dates
        else 'No reports yet'
    )
    page = (
        _INDEX_TEMPLATE.replace('__TITLE__', html.escape(SITE_TITLE))
        .replace(
            '__TEAM_SPAN__',
            f'<span class="team">{html.escape(SITE_TEAM)}</span>' if SITE_TEAM else '',
        )
        .replace('__META__', meta)
        .replace('__STARRED__', STARRED_REPORT)
        .replace('__DATA__', json.dumps(data, ensure_ascii=False).replace('</', '<\\/'))
    )
    _write_atomic(os.path.join(REPORTS_DIR, 'index.html'), page, encoding='utf-8')

    target = report_file(dates[0]) if dates else 'index.html'
    with open(os.path.join(REPORTS_DIR, 'latest.html'), 'w', encoding='utf-8') as f:
        f.write(
            f'<!DOCTYPE html><meta charset="utf-8"><meta http-equiv="refresh" content="0; url={target}">'
            f'<link rel="canonical" href="{target}"><a href="{target}">Latest report</a>\n'
        )
    open(os.path.join(REPORTS_DIR, '.nojekyll'), 'w').close()
    print(f'🗂️  Site built: {len(dates)} day(s), {len(weeks)} week(s), {len(months)} month(s).')


if __name__ == '__main__':
    build()
