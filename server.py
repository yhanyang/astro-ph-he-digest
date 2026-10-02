"""FastAPI web UI for the arxiv_report daily report generator."""

import asyncio
import datetime
import glob
import html as _html
import ipaddress
import os
import re
import threading
import time
import uuid

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from core import corpus, feedback as _feedback, promote as _promote
from core.config import FALLBACK_ORDER, OPENAI_BACKEND, PREFERRED_PROVIDER, SITE_TEAM
from core.fetcher import (
    ARXIV_COOLDOWN_PATH,
    ARXIV_COOLDOWN_SECONDS,
    ARXIV_TZ,
    describe_empty_window,
    fetch_arxiv_papers,
)
from core.providers import generate_report
from core.render import FRAGMENTS_DIR, REPORTS_DIR, STARRED_REPORT, save_html
from core.sanity import DEFAULT_C, attach, search_rank, similar_rank, svm_rank, time_filter

_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
_REPORT_FILENAME_RE = re.compile(r'arXiv_astro_ph_HE_daily_report_(\d{4}-\d{2}-\d{2})\.html$')


def _parse_date(s: str) -> datetime.date | None:
    """Strict YYYY-MM-DD parser. Returns None on any deviation.

    ``datetime.date.fromisoformat`` accepts `2026-05-22T12:00`-style
    suffixes -- we reject those with an explicit regex pre-check so
    that URLs like ``/r/2026-05-22T12:00`` cannot smuggle anything
    extra past the filename concatenation.
    """
    if not _DATE_RE.match(s):
        return None
    try:
        return datetime.date.fromisoformat(s)
    except ValueError:
        return None


def _list_recent_dates(limit: int = 30) -> list[datetime.date]:
    """Return dates of existing reports, newest first, capped at ``limit``.

    Filenames not matching ``arXiv_astro_ph_HE_daily_report_YYYY-MM-DD.html``
    are silently ignored.
    """
    out: list[datetime.date] = []
    for path in glob.glob(os.path.join(REPORTS_DIR, 'arXiv_astro_ph_HE_daily_report_*.html')):
        m = _REPORT_FILENAME_RE.search(os.path.basename(path))
        if not m:
            continue
        d = _parse_date(m.group(1))
        if d:
            out.append(d)
    out.sort(reverse=True)
    return out[:limit]


def _report_path(date: datetime.date) -> str:
    """Filesystem path for the report HTML on this date."""
    return os.path.join(REPORTS_DIR, f'arXiv_astro_ph_HE_daily_report_{date.isoformat()}.html')


def _file_version(path: str) -> str:
    """Cache-busting token for generated HTML iframe URLs."""
    try:
        return str(int(os.path.getmtime(path) * 1000))
    except OSError:
        return str(int(time.time() * 1000))


def _raw_html_response(path: str) -> FileResponse:
    """Serve generated HTML without browser caching stale iframe content."""
    return FileResponse(
        path,
        media_type='text/html',
        headers={
            'Cache-Control': 'no-store, max-age=0',
            'Pragma': 'no-cache',
            'Expires': '0',
        },
    )


def _arxiv_cooldown_remaining() -> int:
    """Seconds until the arXiv rate-limit cooldown expires; 0 if not active.

    The cooldown file is written by ``core.fetcher`` whenever the arXiv API
    returns HTTP 429, regardless of whether the requesting window was recent
    or historical. While the cooldown is active, the UI disables Generate
    instead of letting the user hammer arXiv into a longer block.
    """
    try:
        with open(ARXIV_COOLDOWN_PATH) as f:
            until = float(f.read().strip())
    except (FileNotFoundError, ValueError, OSError):
        return 0
    return max(0, int(until - time.time()))


def _humanize_fetch_error(exc: Exception) -> str:
    """Trim ugly arXiv API exception text to something humans want to read."""
    msg = str(exc)
    if 'cooldown active' in msg.lower():
        return msg  # already formatted by core.fetcher
    if '429' in msg:
        mins = (ARXIV_COOLDOWN_SECONDS + 59) // 60
        return f'arXiv API is rate-limiting requests. Cooldown set; retry in up to {mins} min.'
    return msg


_tasks: dict[str, dict] = {}
# task_id -> {
#   'status':      'running' | 'done' | 'error',
#   'date':        'YYYY-MM-DD',
#   'messages':    list[str],
#   'report_path': str | None,
#   'provider':    str | None,
#   'error':       str | None,
#   'empty_reason': str | None,  # set when a 'done' task found no papers
# }


def _worker(task_id: str, as_of: datetime.datetime, date_str: str) -> None:
    """Run the full fetch -> LLM -> save flow, updating ``_tasks[task_id]``.

    Each stage appends a one-line status message to ``task['messages']``
    so the SSE stream can surface progress incrementally. Exceptions in
    any stage land in ``task['error']`` and set ``status='error'``.
    """
    task = _tasks[task_id]
    task['messages'].append(f'Task: {task_id[:8]} · Date: {date_str}')
    task['messages'].append(
        'Provider preference: '
        f'{PREFERRED_PROVIDER}; fallback: {", ".join(FALLBACK_ORDER) or "none"}; '
        f'OpenAI backend: {OPENAI_BACKEND}'
    )
    task['messages'].append(f'Fetch anchor: {as_of.isoformat()}')
    task['messages'].append('Fetching arXiv papers...')
    try:
        papers = fetch_arxiv_papers(as_of=as_of)
    except Exception as exc:
        clean = _humanize_fetch_error(exc)
        task['error'] = clean
        task['status'] = 'error'
        task['messages'].append(f'Fetch failed: {clean}')
        return

    task['messages'].append(f'Found {len(papers)} papers')
    if not papers:
        reason = describe_empty_window(as_of=as_of)
        task['empty_reason'] = reason
        task['status'] = 'done'
        task['messages'].append(f'No papers: {reason}')
        return

    try:
        added = corpus.upsert_papers(papers, date_str)
        task['messages'].append(f'Corpus: {added} new papers added ({corpus.stats()["n"]} total)')
    except Exception as exc:  # the corpus is a convenience; never block the report
        task['messages'].append(f'Corpus update skipped: {exc}')

    task['messages'].append('Calling LLM (may take several minutes)...')
    try:
        report, provider = generate_report(papers)
    except Exception as exc:
        task['error'] = str(exc)
        task['status'] = 'error'
        task['messages'].append(f'LLM failed: {exc}')
        return

    task['provider'] = provider
    task['messages'].append(f'Provider: {provider}')
    task['report_path'] = save_html(papers, report, provider, as_of=as_of)
    task['messages'].append(f'Output: {task["report_path"]}')
    task['status'] = 'done'
    task['messages'].append('Done.')


app = FastAPI(title='arXiv · astro-ph.HE')

# --- network access control -----------------------------------------------------------
# The UI may be bound to all interfaces for the lab network (HOST=0.0.0.0 in env.sh). Requests
# are then accepted only from ALLOWED_NETS (comma-separated CIDRs; default: this machine only),
# and, when UI_TOKEN is set, writes (POST: feedback, notes, promote, generate) additionally need
# the token, granted once per browser via /unlock?token=... (cookie).
_ALLOWED_NETS = [
    ipaddress.ip_network(x.strip(), strict=False)
    for x in os.getenv('ALLOWED_NETS', '127.0.0.1/32,::1/128').split(',')
    if x.strip()
]
_UI_TOKEN = os.getenv('UI_TOKEN', '').strip()


def _client_allowed(host: str | None) -> bool:
    try:
        ip = ipaddress.ip_address((host or '').split('%')[0])
    except ValueError:
        return False
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return any(ip in net for net in _ALLOWED_NETS)


def _write_allowed(request: Request) -> bool:
    if not _UI_TOKEN:
        return True
    return (
        request.cookies.get('ui_token') == _UI_TOKEN
        or request.headers.get('X-UI-Token') == _UI_TOKEN
    )


@app.middleware('http')
async def _access_control(request: Request, call_next):
    if not _client_allowed(request.client.host if request.client else None):
        return PlainTextResponse('Forbidden: this address is not in ALLOWED_NETS.', status_code=403)
    if request.method not in ('GET', 'HEAD', 'OPTIONS') and not _write_allowed(request):
        if request.url.path.startswith('/unlock'):
            return await call_next(request)
        return JSONResponse(
            {
                'ok': False,
                'error': 'Read-only access: open /unlock?token=<UI_TOKEN> once in this browser to enable 👍/👎, notes and report generation.',
            },
            status_code=401,
        )
    return await call_next(request)


@app.get('/unlock', response_model=None)
def unlock(token: str = '') -> RedirectResponse | PlainTextResponse:
    """Store the write token in a cookie (one year) and go to the home page."""
    if not _UI_TOKEN:
        return RedirectResponse('/', status_code=303)
    if token != _UI_TOKEN:
        return PlainTextResponse('Wrong token.', status_code=403)
    resp = RedirectResponse('/', status_code=303)
    resp.set_cookie('ui_token', token, max_age=365 * 86400, httponly=True, samesite='lax')
    return resp


templates = Jinja2Templates(directory='templates')
templates.env.globals['SITE_TEAM'] = SITE_TEAM


def _render_home(
    request: Request, selected_date: datetime.date | None, main_content: str
) -> HTMLResponse:
    """Render ``home.html`` with the given main-area content."""
    return templates.TemplateResponse(
        request=request,
        name='home.html',
        context={
            'selected_date': selected_date,
            'main_content': main_content,
            'controls_html': _render_controls(selected_date),
        },
        headers={
            'Cache-Control': 'no-store, max-age=0',
            'Pragma': 'no-cache',
            'Expires': '0',
        },
    )


def _render_partial(name: str, **ctx) -> str:
    """Render a partial template to a string (no Response wrapping)."""
    return templates.get_template(name).render(**ctx)


def _render_controls(selected_date: datetime.date | None) -> str:
    """Render the sidebar Generate-form fragment, accounting for cooldown."""
    return _render_partial(
        'partials/controls.html',
        selected_date=selected_date,
        cooldown_remaining=_arxiv_cooldown_remaining(),
    )


def _terminal_fragment(task: dict) -> str:
    """The HTML fragment shipped in the SSE 'done' event."""
    if task['status'] == 'error':
        return _render_partial(
            'partials/error_panel.html', message=task['error'] or 'Unknown error'
        )
    if task['report_path'] is None:
        return _render_partial(
            'partials/empty_panel.html',
            date=task['date'],
            reason=task.get('empty_reason'),
        )
    return _render_partial(
        'partials/report_frame.html',
        date=task['date'],
        raw_version=_file_version(task['report_path']),
    )


def _sse_pack_fragment(event: str, html: str) -> str:
    """Encode a possibly-multiline HTML fragment as a single SSE event.

    Each newline becomes a separate ``data:`` line; the browser
    reassembles them with newline separators back into the same HTML.
    """
    lines = html.replace('\r\n', '\n').split('\n')
    data_block = '\n'.join(f'data: {line}' for line in lines)
    return f'event: {event}\n{data_block}\n\n'


app.mount('/static', StaticFiles(directory='static'), name='static')
# The static GitHub Pages site (index.html with Today / This Week / This Month, summaries, wiki),
# so that forwarding this single port is enough to browse everything from another machine.
app.mount('/site', StaticFiles(directory=REPORTS_DIR, check_dir=False, html=True), name='site')
# HTML export of the Obsidian wiki (written by `wiki.py html` into reports/wiki).
app.mount(
    '/wiki',
    StaticFiles(directory=os.path.join(REPORTS_DIR, 'wiki'), check_dir=False, html=True),
    name='wiki',
)


@app.get('/', response_model=None)
def index(request: Request) -> HTMLResponse | RedirectResponse:
    """Open the tabbed site (Day / Week / Month / Year) when it exists, else the latest report."""
    if os.path.exists(os.path.join(REPORTS_DIR, 'index.html')):
        return RedirectResponse(url='/site/')
    dates = _list_recent_dates(limit=1)
    if dates:
        return RedirectResponse(url=f'/r/{dates[0].isoformat()}')
    main = _render_partial('partials/placeholder.html', date='any date')
    return _render_home(request, None, main)


@app.get('/r/{date}', response_class=HTMLResponse)
def report_page(date: str, request: Request) -> HTMLResponse:
    """Main page for a specific date. Renders even when the file is missing."""
    parsed = _parse_date(date)
    if parsed is None:
        raise HTTPException(status_code=400, detail='Invalid date')
    path = _report_path(parsed)
    if os.path.exists(path):
        main = _render_partial(
            'partials/report_frame.html',
            date=parsed.isoformat(),
            raw_version=_file_version(path),
        )
    else:
        main = _render_partial('partials/placeholder.html', date=parsed.isoformat())
    return _render_home(request, parsed, main)


@app.get('/r/{date}/raw')
def report_raw(date: str) -> FileResponse:
    """Serve the raw report HTML for the iframe ``src``."""
    if date == 'week':
        return week_raw()
    parsed = _parse_date(date)
    if parsed is None:
        raise HTTPException(status_code=400, detail='Invalid date')
    path = _report_path(parsed)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail='Report not found')
    return _raw_html_response(path)


@app.get('/starred', response_class=HTMLResponse)
def starred_page(request: Request) -> HTMLResponse:
    """Main page for the browser-local starred/Craft collection."""
    path = os.path.join(REPORTS_DIR, STARRED_REPORT)
    main = _render_partial('partials/starred_frame.html', raw_version=_file_version(path))
    return _render_home(request, None, main)


@app.get('/starred/raw')
def starred_raw() -> FileResponse:
    """Serve the standalone browser-local starred/Craft collection."""
    path = os.path.join(REPORTS_DIR, STARRED_REPORT)
    if not os.path.exists(path):
        from core.render import _write_starred_html

        _write_starred_html(provider='local')
    return _raw_html_response(path)


@app.post('/generate', response_class=HTMLResponse)
def generate(date: str = Form(...)) -> HTMLResponse:
    """Spawn a background generation task and return the running panel."""
    parsed = _parse_date(date)
    if parsed is None:
        raise HTTPException(status_code=400, detail='Invalid date')

    cooldown_s = _arxiv_cooldown_remaining()
    if cooldown_s > 0:
        mins = (cooldown_s + 59) // 60
        msg = f'arXiv API is rate-limiting requests. Cooldown active; retry in ~{mins} min.'
        return HTMLResponse(_render_partial('partials/error_panel.html', message=msg))

    as_of = ARXIV_TZ.localize(datetime.datetime.combine(parsed, datetime.time(hour=12)))
    task_id = str(uuid.uuid4())
    _tasks[task_id] = {
        'status': 'running',
        'date': parsed.isoformat(),
        'messages': [],
        'report_path': None,
        'provider': None,
        'error': None,
    }
    threading.Thread(target=_worker, args=(task_id, as_of, parsed.isoformat()), daemon=True).start()
    html = _render_partial('partials/status_panel.html', task_id=task_id)
    return HTMLResponse(html)


@app.get('/generate/stream/{task_id}')
async def generate_stream(task_id: str, request: Request) -> StreamingResponse:
    """SSE: stream worker log lines, then a single 'done' event with the result."""

    async def gen():
        sent = 0
        while True:
            if await request.is_disconnected():
                break
            task = _tasks.get(task_id)
            if task is None:
                yield _sse_pack_fragment(
                    'done',
                    '<div class="alert alert-error">Task not found.</div>',
                )
                return
            while sent < len(task['messages']):
                safe = _html.escape(task['messages'][sent])
                sent += 1
                yield f'data: <div class="log-line">{safe}</div>\n\n'
            if task['status'] in ('done', 'error'):
                yield _sse_pack_fragment('done', _terminal_fragment(task))
                return
            await asyncio.sleep(0.5)

    return StreamingResponse(
        gen(),
        media_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


@app.get('/recent', response_class=HTMLResponse)
def recent(active: str = '') -> HTMLResponse:
    """Sidebar fragment: list of recent report dates, descending."""
    dates = _list_recent_dates(limit=30)
    html = _render_partial('partials/recent_list.html', dates=dates, active=active)
    return HTMLResponse(html)


@app.get('/controls', response_class=HTMLResponse)
def controls(active: str = '') -> HTMLResponse:
    """Sidebar Generate-form fragment; polled to reflect cooldown state."""
    selected = _parse_date(active)
    return HTMLResponse(_render_controls(selected))


# --- arxiv-sanity-lite style search / similar / recommendations ---------------
_PID_RE = re.compile(r'^(\d{4}\.\d{4,5}|[a-z\-]+(?:\.[A-Z]{2})?/\d{7})(v\d+)?$')


def _bare_pid(raw: str) -> str | None:
    """Validate an arXiv id from a URL path and drop any version suffix."""
    m = _PID_RE.match(raw.strip())
    return m.group(1) if m else None


def _full_entry_numbers(date: str) -> set[int]:
    """Numbers of the papers that have a full (non abstract-only) entry in ``date``'s fragment."""
    path = os.path.join(FRAGMENTS_DIR, f'{date}.html')
    if not os.path.exists(path):
        return set()
    with open(path, encoding='utf-8') as f:
        return {int(n) for n in re.findall(r'<div class="paper-item" id="p(\d+)"', f.read())}


def _attach(pids: list[str], scores: list[float]) -> list[dict]:
    """``attach`` plus what the action row needs: verdict, note, display id, full-entry flag."""
    from core.prompt import _arxiv_display_id

    papers = attach(pids, scores)
    verdicts = _feedback.all_verdicts()
    notes = _feedback.all_notes()
    full: dict[str, set[int]] = {}
    for p in papers:
        d = p.get('report_date', '')
        if d not in full:
            full[d] = _full_entry_numbers(d)
        p['verdict'] = verdicts.get(p['pid'], '')
        p['note'] = notes.get(p['pid'], '')
        p['display_id'] = _arxiv_display_id(p.get('url', ''))
        p['full'] = p.get('number') in full[d]
    return papers


def _sanity_page(request: Request, **ctx) -> HTMLResponse:
    ctx.setdefault('corpus_stats', corpus.stats())
    main = _render_partial('partials/sanity_page.html', **ctx)
    return _render_home(request, None, main)


@app.get('/search', response_class=HTMLResponse)
def search_page(request: Request, q: str = '', days: int = 0) -> HTMLResponse:
    """Keyword search across every paper this instance has ever fetched."""
    q = q.strip()
    pids, scores = time_filter(*search_rank(q), days) if q else ([], [])
    return _sanity_page(request, kind='search', q=q, days=days, papers=_attach(pids, scores)[:200])


@app.get('/similar/{pid}', response_class=HTMLResponse)
def similar_page(pid: str, request: Request, days: int = 0) -> HTMLResponse:
    """Papers most similar (TF-IDF cosine) to one arXiv id."""
    bare = _bare_pid(pid)
    if bare is None:
        raise HTTPException(status_code=400, detail='Invalid arXiv id')
    anchor = corpus.get_paper(bare)
    pids, scores = time_filter(*similar_rank(bare), days)
    return _sanity_page(
        request,
        kind='similar',
        anchor=anchor,
        pid=bare,
        days=days,
        papers=_attach(pids, scores)[:50],
    )


@app.get('/liked', response_class=HTMLResponse)
def liked_page(request: Request, days: int = 0) -> HTMLResponse:
    """Every 👍 liked paper (server-side verdicts), newest listing first."""
    pids = _feedback.liked()
    ordered = sorted(
        corpus.get_papers(pids).values(),
        key=lambda p: (p['report_date'], p['number']),
        reverse=True,
    )
    pids = [p['pid'] for p in ordered]
    pids, scores = time_filter(pids, [0.0] * len(pids), days)
    papers = _attach(pids, scores)
    return _sanity_page(request, kind='liked', days=days, papers=papers, n_liked=len(ordered))


@app.get('/recommend', response_class=HTMLResponse)
def recommend_page(request: Request, days: int = 0) -> HTMLResponse:
    """SVM recommendations seeded by the browser's starred papers (filled client-side)."""
    return _sanity_page(request, kind='recommend', days=days, papers=None)


class RecommendRequest(BaseModel):
    pids: list[str]
    days: int = 0
    C: float = DEFAULT_C
    source: str = 'both'  # 'both' | 'starred' | 'liked'


@app.post('/recommend/rank', response_class=HTMLResponse)
def recommend_rank(req: RecommendRequest) -> HTMLResponse:
    """Train the SVM on the posted positive ids and return the ranked list fragment."""
    source = req.source if req.source in ('both', 'starred', 'liked') else 'both'
    starred = [b for b in (_bare_pid(x) for x in req.pids) if b] if source != 'liked' else []
    liked = _feedback.liked() if source != 'starred' else []
    dismissed = _feedback.dismissed()  # 👎 papers are never positives and never recommended
    positives = [p for p in dict.fromkeys([*starred, *liked]) if p not in dismissed]
    if not positives:
        return HTMLResponse(
            _render_partial(
                'partials/sanity_results.html',
                papers=[],
                words=[],
                kind='recommend',
                empty_hint='no-positives',
                source=source,
            )
        )
    C = min(max(req.C, 1e-4), 10.0)
    pids, scores, words = svm_rank(positives, C=C)
    pids, scores = time_filter(pids, scores, req.days)
    known = corpus.get_papers(positives)
    papers = [
        p for p in _attach(pids, scores) if p['pid'] not in known and p['pid'] not in dismissed
    ][:100]
    return HTMLResponse(
        _render_partial(
            'partials/sanity_results.html',
            papers=papers,
            words=words,
            kind='recommend',
            source=source,
            n_positive=len(known),
            n_unknown=len(positives) - len(known),
            n_starred=sum(1 for x in set(starred) if x in known),
            n_liked=sum(1 for x in set(liked) if x in known),
        )
    )


# --- week / month summaries ------------------------------------------------------
_SUMMARY_NAME_RE = re.compile(r'^(?:week|month|year)(?:-(?:\d{4}-W\d{2}|\d{4}-\d{2}|\d{4}))?$')


def _summary_path(name: str) -> str:
    if not _SUMMARY_NAME_RE.match(name):
        raise HTTPException(status_code=400, detail='Unknown summary')
    return os.path.join(REPORTS_DIR, f'{name}.html')


@app.get('/s/{name}', response_class=HTMLResponse)
def summary_page(name: str, request: Request) -> HTMLResponse:
    """Week or month summary: ``week``, ``month``, ``week-2026-W40``, ``month-2026-10``."""
    path = _summary_path(name)
    if os.path.exists(path):
        main = _render_partial(
            'partials/summary_frame.html', summary=name, raw_version=_file_version(path)
        )
    else:
        main = _render_partial('partials/placeholder.html', date=name)
    return _render_home(request, None, main)


@app.get('/s/{name}/raw')
def summary_raw(name: str) -> FileResponse:
    path = _summary_path(name)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail='No such summary yet')
    return _raw_html_response(path)


@app.get('/week', response_model=None)
def week_page() -> RedirectResponse:
    return RedirectResponse(url='/s/week')


@app.get('/week/raw')
def week_raw() -> FileResponse:
    return summary_raw('week')


# --- promote an "Other topics" entry to a full digest ------------------------------
@app.post('/promote/{date}/{pid}')
def promote_paper(date: str, pid: str) -> JSONResponse:
    """Run the LLM on one paper and upgrade its report entry (synchronous, ~1 min)."""
    parsed = _parse_date(date)
    bare = _bare_pid(pid)
    if parsed is None or bare is None:
        raise HTTPException(status_code=400, detail='Invalid date or arXiv id')
    try:
        info = _promote.promote(parsed.isoformat(), bare)
    except Exception as exc:
        return JSONResponse({'ok': False, 'error': str(exc)}, status_code=500)
    return JSONResponse({'ok': True, **info})


_SITE_BUILD_LOCK = threading.Lock()
_SITE_BUILD_PENDING = threading.Event()


def _schedule_site_build() -> None:
    """Rebuild the static site in a background thread; coalesces bursts of requests."""
    _SITE_BUILD_PENDING.set()

    def run() -> None:
        with _SITE_BUILD_LOCK:
            if not _SITE_BUILD_PENDING.is_set():
                return
            _SITE_BUILD_PENDING.clear()
            import build_site

            try:
                build_site.build()
            except Exception as exc:  # logged, never raised into a request
                print(f'[site] background build failed: {exc}')

    threading.Thread(target=run, daemon=True).start()


# --- 👍 / 👎 feedback ----------------------------------------------------------------
@app.post('/feedback/{date}/{pid}/{verdict}')
def feedback_route(date: str, pid: str, verdict: str) -> JSONResponse:
    """Record like / dislike / clear for one paper and re-render that day's report.

    A like on an abstract-only entry also promotes it to a full digest (synchronous LLM call).
    """
    parsed = _parse_date(date)
    bare = _bare_pid(pid)
    if parsed is None or bare is None or verdict not in ('like', 'dislike', 'clear'):
        raise HTTPException(status_code=400, detail='Invalid date, arXiv id or verdict')
    try:
        _feedback.set_verdict(bare, None if verdict == 'clear' else verdict)
        info = {'date': parsed.isoformat(), 'pid': bare, 'verdict': verdict}
        if verdict == 'like' and not _promote.has_full_entry(parsed.isoformat(), bare):
            info.update(_promote.promote(parsed.isoformat(), bare, rebuild=False))
            info['promoted'] = True
        _promote.rerender(parsed.isoformat())
    except Exception as exc:
        return JSONResponse({'ok': False, 'error': str(exc)}, status_code=500)
    _schedule_site_build()  # summaries and ★ counts catch up in the background (~2 s)
    return JSONResponse({'ok': True, **info})


class NoteRequest(BaseModel):
    text: str = ''


@app.post('/note/{date}/{pid}')
def note_route(date: str, pid: str, req: NoteRequest) -> JSONResponse:
    """Store (or delete, when empty) the personal note of one paper and re-render that day."""
    parsed = _parse_date(date)
    bare = _bare_pid(pid)
    if parsed is None or bare is None:
        raise HTTPException(status_code=400, detail='Invalid date or arXiv id')
    try:
        _feedback.set_note(bare, req.text[:5000])
        _promote.rerender(parsed.isoformat())
    except Exception as exc:
        return JSONResponse({'ok': False, 'error': str(exc)}, status_code=500)
    return JSONResponse({'ok': True, 'pid': bare, 'has_note': bool(req.text.strip())})
