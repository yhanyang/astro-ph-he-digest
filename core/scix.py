"""Minimal NASA SciX (Science Explorer, the successor of ADS) API client: citation counts
for arXiv ids.

A free token is required (https://scixplorer.org/user/settings/token; an ADS token works
too). It is read from ``SCIX_API_TOKEN`` (fallbacks: ``ADS_API_TOKEN``, ``ADS_DEV_KEY``,
``~/.scix/token``, ``~/.ads/dev_key``). The search API allows 5000 requests per day; one
request here resolves up to ``CHUNK`` papers. The API host can be overridden with
``SCIX_API_URL`` should SciX move it off the historical ADS hostname.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

API_URL = os.getenv('SCIX_API_URL', 'https://api.adsabs.harvard.edu/v1/search/query')
ABS_URL = 'https://scixplorer.org/abs/{bibcode}/abstract'
TOKEN_PAGE = 'https://scixplorer.org/user/settings/token'
CHUNK = 40  # arXiv ids per request (keeps the query well under the URL length limit)
FIELDS = 'bibcode,identifier,citation_count,read_count,pubdate,property,doctype,pub'
_ARXIV_RE = re.compile(r'^(?:arXiv:)?(\d{4}\.\d{4,5})(?:v\d+)?$', re.I)
_OLD_ARXIV_RE = re.compile(r'^(?:arXiv:)?([a-z\-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?$', re.I)


class ScixError(RuntimeError):
    pass


class ScixRateLimit(ScixError):
    def __init__(self, reset_ts: float | None):
        super().__init__('SciX rate limit reached')
        self.reset_ts = reset_ts


def token() -> str | None:
    for var in ('SCIX_API_TOKEN', 'ADS_API_TOKEN', 'ADS_DEV_KEY'):
        tok = os.getenv(var)
        if tok and tok.strip():
            return tok.strip()
    for path in ('~/.scix/token', '~/.ads/dev_key'):
        path = os.path.expanduser(path)
        if os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                tok = f.read().strip()
            if tok:
                return tok
    return None


def bare_arxiv_id(ident: str) -> str | None:
    """``'arXiv:2609.01644v2'`` -> ``'2609.01644'`` (also old-style ids); else ``None``."""
    m = _ARXIV_RE.match(ident.strip()) or _OLD_ARXIV_RE.match(ident.strip())
    return m.group(1) if m else None


def _get_json(url: str, tok: str) -> tuple[dict, dict]:
    req = urllib.request.Request(
        url, headers={'Authorization': f'Bearer {tok}', 'User-Agent': 'astro-ph-he-digest/1.0'}
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode('utf-8')), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            reset = exc.headers.get('X-RateLimit-Reset')
            raise ScixRateLimit(float(reset) if reset else None) from exc
        if exc.code == 401:
            raise ScixError('SciX rejected the token (401). Check SCIX_API_TOKEN.') from exc
        raise ScixError(f'SciX HTTP {exc.code}: {exc.read()[:200]!r}') from exc
    except urllib.error.URLError as exc:
        raise ScixError(f'SciX unreachable: {exc.reason}') from exc


def query_arxiv_ids(ids: list[str], tok: str | None = None) -> dict[str, dict]:
    """Return ``{arxiv_id: record}`` for the ids SciX knows (one request per ``CHUNK`` ids).

    ``record`` has ``bibcode``, ``citation_count``, ``read_count``, ``pubdate``, ``refereed``,
    ``doctype`` and ``pub``. Ids may carry a version suffix; keys are bare ids.
    """
    tok = tok or token()
    if not tok:
        raise ScixError(f'No SciX token: set SCIX_API_TOKEN (get one at {TOKEN_PAGE}).')
    wanted = {bare_arxiv_id(i) or i: i for i in ids}
    out: dict[str, dict] = {}
    keys = list(wanted)
    for start in range(0, len(keys), CHUNK):
        chunk = keys[start : start + CHUNK]
        q = 'identifier:(' + ' OR '.join(f'"arXiv:{i}"' for i in chunk) + ')'
        params = urllib.parse.urlencode({'q': q, 'fl': FIELDS, 'rows': 2 * len(chunk)})
        data, headers = _get_json(f'{API_URL}?{params}', tok)
        for doc in data.get('response', {}).get('docs', []):
            hit = None
            for ident in doc.get('identifier', []) or []:
                b = bare_arxiv_id(ident)
                if b and b in wanted:
                    hit = b
                    break
            if hit is None:
                continue
            rec = {
                'bibcode': doc.get('bibcode', ''),
                'citation_count': int(doc.get('citation_count') or 0),
                'read_count': int(doc.get('read_count') or 0),
                'pubdate': doc.get('pubdate', ''),
                'refereed': 'REFEREED' in (doc.get('property') or []),
                'doctype': doc.get('doctype', ''),
                'pub': doc.get('pub', ''),
            }
            # SciX normally merges the arXiv and journal versions; keep the richer record otherwise.
            if hit not in out or rec['citation_count'] > out[hit]['citation_count']:
                out[hit] = rec
        remaining = headers.get('X-RateLimit-Remaining')
        if remaining is not None and remaining.isdigit() and int(remaining) < 5:
            reset = headers.get('X-RateLimit-Reset')
            raise ScixRateLimit(float(reset) if reset else None)
        if start + CHUNK < len(keys):
            time.sleep(0.25)
    return out
