# arXiv High-Energy Astrophysics Daily Report Generator

Automatically fetches the latest papers from the arXiv `astro-ph.HE` (High Energy Astrophysical Phenomena) category, uses a large language model to generate a structured academic digest, and exports it as an HTML report. Ships with a CLI for cron / one-off runs and a FastAPI + HTMX web UI for browsing past reports and triggering new ones interactively.


## Daily team site on GitHub Pages

The workflow in `.github/workflows/daily-report.yml` runs Monday to Friday at 02:30 UTC, which is 1.5–2.5 h after arXiv's 20:00 ET announcement (04:30 in Rome in summer, 03:30 in winter). Each run fetches the new astro-ph.HE listing through the arXiv API, generates the English report, rebuilds the site, and pushes it to the `gh-pages` branch.

What the team sees at `https://<user>.github.io/<repo>/`:

- a header **arXiv · astro-ph.HE** (an optional team name can be appended via `SITE_TEAM`) with four tabs (Day / Week / Month / Year):
  - **Day** — the latest listing by default, ‹ › to step through days and a calendar picker (days with a report are clickable);
  - **Week** — the week summary (highlights, topic statistics, per-topic paper lists), ‹ › to move between weeks, and a calendar picker where whole ISO-week rows select a week and single days jump to the Day tab;
  - **Month** — the month summary, ‹ › to move between months, and a year-grid month picker;
  - **Year** — the year summary (topic × month statistics, highlights grouped by month, per-topic lists), ‹ › between years and a year picker;
  - every view has an *open standalone ↗* link, and a notice with a direct link appears if the embedded frame cannot load;
- every view is a URL: `#day` (latest), `#day/2026-09-29`, `#day/2026-09-29/p13` (scrolled to paper 13), `#week/2026-W40`, `#month/2026-10`, `#year/2026`; the older `#2026-09-29/p13` form still works;
- inside each daily report the **Field Index** is a row of coloured chips with abbreviations (GW · GRB · EFXT · FRB · KN · TDE · QPE · MAG, then the dashed index-only chips) and counts; click a chip to filter the papers, open *Numbered index* for the classic list;
- **My starred papers**, saved in each reader's own browser; the 📚 **Wiki** (one HTML page per paper, topic, object, day and week) linked from every paper entry.

One-time setup:

1. **Add an API key.** *Settings → Secrets and variables → Actions → New repository secret*: add `CLAUDE_API_KEY` (or `GEMINI_API_KEY` / `OPENAI_API_KEY`, and set the repository variable `PREFERRED_PROVIDER` to `gemini` or `openai`).
2. **Optional variables** (*Variables* tab): `CLAUDE_MODEL` / `GEMINI_MODEL` / `OPENAI_MODEL`, `FALLBACK_ORDER` (e.g. `claude,gemini`), `SITE_TITLE` and `SITE_TEAM`. The workflow keeps the paper corpus and the wiki vault inside the `gh-pages` branch (`reports/.data`, `reports/.wiki`) so search, similar-paper and wiki pages work on the published site too.
3. **Run it once.** *Actions → Daily arXiv report → Run workflow*. The first run creates the `gh-pages` branch.
4. **Turn on Pages.** *Settings → Pages → Deploy from a branch → `gh-pages` / `(root)`*.

To backfill a missing day, run the workflow manually and enter the listing date exactly as arXiv shows it (e.g. `2026-09-24`); run it once per day. Leave the date empty to fetch the latest announcement.

On a public repository the Pages site is public. The "Save to Craft" buttons are hidden unless you set `CRAFT_SPACE_ID` and `CRAFT_ARXIV_FOLDER_ID`.

## Features

- Fetches newly submitted papers based on arXiv's submission sync window (US Eastern Time)
- Supports arbitrary historical dates via arXiv's `submittedDate` range query
- Two-tier taxonomy: eight focus topics (compact mergers & GW first, GRBs, EFXTs, FRBs, kilonovae, TDEs, QPEs, magnetars) get full digests; twelve index-only topics (SNe, FBOTs, neutron stars, pulsars, black holes & accretion, jets & blazars, cosmic rays, VHE, SNRs/ISM, machine learning, theory & instrumentation, misc) are indexed with title and abstract only and can be promoted later
- Generates English-language summaries with method tags and key physical findings
- Multi-provider LLM dispatch: OpenAI Codex CLI / API by default, with optional Claude (CLI or API) and Gemini fallback
- Self-contained styled HTML reports (light / dark adaptive, internal anchor scrolling)
- FastAPI + HTMX web UI: per-date URLs, sidebar history, live SSE progress
- Per-paper "Save to Craft" button: hands off a new Craft document (title, authors, method/results/caveats, optional personal note) via the `craftdocs://` URL scheme
- Obsidian wiki (claude-obsidian style): one note per paper with the LLM digest, topic and object Maps of Content, daily and weekly notes, preserved sources, an operations journal and a linter; human edits survive every rebuild
- arxiv-sanity-lite features on top of the daily reports: a persistent paper corpus, keyword search across all days, TF-IDF "similar papers", and SVM recommendations trained on your starred papers (web UI + CLI)

## Project layout

```
.
├── server.py              FastAPI app, routes, background worker, SSE stream
├── report.py              CLI entry (cron / one-off)
├── sanity.py              CLI for search / similar / recommend (arxiv-sanity-lite port)
├── promote.py             upgrade one "Other topics" paper to a full digest
├── citations.py           NASA SciX (ex-ADS) citation counts (status / refresh / top)
├── manual_digest.py       print the exact prompt for a day / validate + save a hand-written digest
├── backfill.sh            generate a date range unattended (nohup-safe), then rebuild site + wiki
├── prefetch.py            slow, resumable fetch of a date range + optional index-only reports
├── phase2_runner.sh       waits for prefetch.py, then runs backfill.sh month by month until done
├── wiki.py                CLI for the Obsidian wiki: build / lint / fold / log
├── build_site.py          static GitHub Pages site from reports/
├── run_report.sh          report.py + build_site.py with the Claude CLI backend (see env.sh)
├── run_server.sh          web UI with the same environment
├── core/                  domain package
│   ├── fetcher.py           arXiv API + RSS fallback
│   ├── providers.py         Claude / Gemini / OpenAI clients + fallback dispatcher
│   ├── prompt.py            prompt builder
│   ├── pub_status.py        publication-status classifier
│   ├── render.py            standalone HTML wrapper
│   ├── topics.py            focus-topic taxonomy shared by prompt / renderer / site / wiki
│   ├── report_post.py       appends Other-topics entries, converts legacy indexes
│   ├── promote.py           single-paper digest + report/site/wiki update
│   ├── indexonly.py         keyword classifier + index-only report fragments (no LLM)
│   ├── corpus.py            SQLite paper corpus accumulated across runs
│   ├── features.py          TF-IDF features (arxiv-sanity-lite compute.py)
│   ├── sanity.py            search_rank / similar_rank / svm_rank (arxiv-sanity-lite serve.py)
│   ├── wiki.py              Obsidian vault builder, linter and weekly fold
│   └── config.py            env vars + defaults
├── templates/             Jinja2 base + partials for the web UI
├── static/style.css       sidebar + main chrome
├── tests/                 pytest suite (31 cases)
├── data/                  papers.db + features.pkl (gitignored)
├── wiki/                  Obsidian vault (papers/ topics/ objects/ daily/ weekly/ Home.md MAINTENANCE.md)
└── reports/               generated daily reports (gitignored)
```

## Installation

```bash
pip install -r requirements.txt
```

For the default ChatGPT/Codex backend, install the Codex CLI and log in once with `codex login`.

## Configuration

Set API keys, models, and provider backends via environment variables (all optional, defaults provided):

| Variable | Description | Default |
|---|---|---|
| `PREFERRED_PROVIDER` | Preferred LLM provider: `openai`, `claude`, or `gemini` | `openai` |
| `FALLBACK_ORDER` | Comma-separated fallback order | `openai` |
| `OPENAI_BACKEND` | `codex` (consumes ChatGPT/Codex subscription via Codex CLI) or `api` (consumes API credits) | `codex` |
| `OPENAI_API_KEY` | OpenAI API key -- only needed when `OPENAI_BACKEND=api` | — |
| `OPENAI_MODEL` | OpenAI/Codex model name | `gpt-5.5` |
| `CODEX_CLI` | Optional absolute path to the Codex CLI; otherwise the ChatGPT-bundled CLI is preferred when available | auto-detected |
| `CLAUDE_BACKEND` | `cli` (consumes Max quota via Claude Code) or `api` (consumes API credits) | `cli` |
| `CLAUDE_API_KEY` | Anthropic Claude API key -- only needed when `CLAUDE_BACKEND=api` | — |
| `CLAUDE_MODEL` | Claude model name (API backend only) | `claude-opus-4-6` |
| `GEMINI_API_KEY` | Google Gemini API key | — |
| `GEMINI_MODEL` | Gemini model name | `gemini-3.1-flash-lite-preview` |
| `CRAFT_SPACE_ID` | Craft space ID for the "Save to Craft" button target folder | maintainer's own space |
| `CRAFT_ARXIV_FOLDER_ID` | Craft folder ID new saved documents are created in | maintainer's own "arxiv Notes" folder |
| `SITE_TEAM` | Optional team / project name appended to the site header, the report kicker and the web UI | *(empty)* |
| `SANITY_DATA_DIR` | Directory for the paper corpus (`papers.db`) and TF-IDF cache (`features.pkl`) | `./data` |
| `SANITY_MAX_FEATURES` | TF-IDF vocabulary size | `20000` |
| `WIKI_DIR` | Obsidian vault directory written by `wiki.py` (point it at an existing vault to embed) | `./wiki` |
| `WIKI_REVIEW_DAYS` | Review window after which curated topic/object overviews are flagged by `wiki.py lint` | `90` |

The Claude CLI backend always uses the `opus` model alias (hardcoded in `core/providers.py`). The preferred LLM provider can be set with `PREFERRED_PROVIDER` (`"openai"`, `"claude"`, or `"gemini"`). Defaults to `"openai"`.

By default, no Claude fallback is attempted, so a normal run only consumes the logged-in ChatGPT/Codex account. To re-enable multi-provider fallback, set for example `FALLBACK_ORDER=openai,claude,gemini`.

## Usage

### CLI

```bash
# Default: today's report via Codex CLI (ChatGPT/Codex subscription)
python report.py

# Generate a report for any historical date (uses arXiv's submittedDate range query)
python report.py --date 2026-03-15

# Switch Claude to the API SDK:
export CLAUDE_BACKEND=api
export CLAUDE_API_KEY="your_api_key_here"
python report.py

# Switch OpenAI to the API SDK:
export OPENAI_BACKEND=api
export OPENAI_API_KEY="your_api_key_here"
python report.py
```

### Backfilling a long range (rate-limit aware, in phases)

```bash
# Phase 0 + 1: slowly fetch every listing day (75 s between arXiv requests, waits out 429 cooldowns,
# resumable) and write an *index-only* report for each day: all papers filed by keyword with title and
# abstract, no LLM. Site, wiki and search cover the range right away. Newest day first.
nohup .venv/bin/python prefetch.py --from 2026-01-01 --to 2026-07-31 --index-only > reports/prefetch.log 2>&1 &

# Phase 2: real digests month by month with the configured LLM backend; index-only days are
# regenerated, days that already have a digest are skipped.
nohup ./backfill.sh 2026-07-01 2026-07-31 > reports/backfill.log 2>&1 &

# Or let a runner do phase 2 automatically: it waits for prefetch.py to finish, then runs backfill.sh
# month by month (newest first), pauses 2 h when the LLM is unavailable (usage limit) and repeats
# passes until no index-only day is left. Progress in reports/phase2.log and reports/backfill-YYYY-MM.log.
setsid nohup ./phase2_runner.sh 2026-01-01 2026-07-31 > reports/phase2.log 2>&1 < /dev/null &
```

Index-only reports are marked (`<!-- index-only -->` in the fragment) and show an *Index-only report* box instead of entries; the Field Index chips, the wiki notes and the search index work as usual, and any paper can be promoted individually.

### Backfilling and writing digests without a provider

```bash
# Every weekday in a range with the configured provider; skips days that already have a report,
# waits out arXiv rate-limit cooldowns, rebuilds site + wiki once at the end. Survives a closed laptop:
nohup ./backfill.sh 2026-09-01 2026-09-25 > reports/backfill.log 2>&1 &

# Write a digest by hand (or paste the prompt into a chat and save the answer):
python manual_digest.py prompt 2026-09-01 --out /tmp/d   # exact prompt + papers for that listing day
python manual_digest.py save   2026-09-01 /tmp/d/frag.html   # validates the HTML body, renders the report, updates the corpus
python build_site.py && python wiki.py fold && python wiki.py build && python wiki.py html
```

`manual_digest.py save` enforces the output contract (every paper indexed, entries only for focus-topic papers, verbatim arXiv links and status badges, required labels, no LaTeX) before anything is written.

### Web UI (FastAPI + HTMX)

```bash
pip install -r requirements.txt
uvicorn server:app --reload --port 8080
```

To run the pipeline automatically on the server, start `setsid nohup ./scheduler.sh > /dev/null 2>&1 &` once: it runs `run_report.sh` Mon–Fri at `RUN_AT` (default 05:00 Europe/Rome, after the 20:00 ET announcement), retries failures every 30 min (4×), keeps the web UI alive (`KEEP_SERVER=1`) and logs to `reports/scheduler.log`; `./scheduler.sh --dry-run` prints the next run, `pkill -f scheduler.sh` stops it.

Then open http://localhost:8080. To share the UI on the lab network set `HOST=0.0.0.0` and `ALLOWED_NETS` (CIDRs that may connect; everyone else gets 403) in `env.local.sh` (git-ignored, sourced by `env.sh`); optionally set `UI_TOKEN` so that only browsers unlocked once via `/unlock?token=…` can write (👍/👎, notes, promote, generate) while others read. The home page is the tabbed site (Day / Week / Month / Year) served at `/site/`; when served by the web UI it loads the reports through `/r/<date>/raw` and the summaries through `/s/…/raw`, so the promote, like/dislike, similar and wiki buttons all work there, and the header links to Search, Recommend and Starred. The same `index.html` on GitHub Pages falls back to plain static files (read-only). `/r/<date>` still opens a report in the sidebar UI; click a date in the sidebar to switch, or pick a fresh date and click **Generate report** to spawn a background generation task with live SSE progress.

For running the web UI as a background macOS service, see [docs/launchagent-setup.md](docs/launchagent-setup.md).

## Search, similar papers & recommendations

These features are a port of [karpathy/arxiv-sanity-lite](https://github.com/karpathy/arxiv-sanity-lite) (MIT) onto the daily-report workflow. The LLM digest stays the primary output; the sanity layer lets you work *across* days.

**How it works**

- Every fetch (CLI or web UI) upserts the papers into a SQLite corpus (`data/papers.db`), remembering the listing date and the `[N]` number so hits deep-link to `/r/<date>#pN`.
- TF-IDF vectors of `title + abstract + authors` (unigrams + bigrams, sublinear tf, l2 norm — the arxiv-sanity-lite `compute.py` settings, with `min_df`/`max_df` relaxed while the corpus is small) are cached in `data/features.pkl` and rebuilt automatically when the corpus changes.
- **Search** ranks literally, with the arxiv-sanity-lite weights: 20 per query word in the title, 10 per word in the author list, up to 3 per occurrence in the abstract.
- **Similar papers** rank by TF-IDF cosine similarity (the ☍ button next to each paper in a report served by the web UI, or `/similar/<arXiv id>`).
- **Recommendations** train `LinearSVC(class_weight='balanced', C=0.01)` with your positives and everything else as negatives, then rank the corpus by decision function. The source selector on the page picks the positives: **★ starred + 👍 liked** (default), starred only, or liked only. Stars are the arxiv-sanity-lite "tags" and live in your browser's `localStorage` (only the arXiv ids are posted to `/recommend/rank`); likes are the server-side 👍 verdicts. 👎 dismissed papers are never used as positives and never recommended. The page also shows the vocabulary terms with the largest positive and negative SVM weights.
- Every view has a time filter (today / 7 / 30 / 90 days / all).

**Web UI**: the sidebar gets a *Search all papers* box and a *Recommended for you* link; routes are `/search?q=…&days=…`, `/similar/<id>`, `/recommend`.

**CLI**

```bash
python sanity.py import-cache                 # backfill the corpus from reports/.cache/*.json
python sanity.py stats
python sanity.py search magnetar FRB --days 30
python sanity.py similar 2609.38341
python sanity.py recommend --ids 2609.38341,2609.38682 --days 7 --words
python sanity.py compute                      # force a TF-IDF rebuild
```

The corpus only contains papers this instance has fetched. On GitHub Actions the corpus is persisted in the `gh-pages` branch, but search/similar/recommend need the FastAPI server and are therefore features of the local web UI and CLI; the wiki HTML is published. Email alerts from arxiv-sanity-lite (`send_emails.py`, SendGrid) are not ported.

## Obsidian wiki and long-term maintenance

`wiki/` is an Obsidian vault built from the daily reports, following the conventions of [AgriciDaniel/claude-obsidian](https://github.com/AgriciDaniel/claude-obsidian): a plain directory of Markdown you own, sources preserved before synthesis, every operation journaled, and a linter that keeps the graph healthy. Open the folder in Obsidian (or any editor); nothing is hidden in a plugin or database.

**Notes**

| Folder | Note | Content (auto) | Yours |
|---|---|---|---|
| `papers/<arXiv id>.md` | one per paper | frontmatter (title, authors, listing day, `[N]`, topics, method tag, status, objects, source hash), the digest sections (research question / methods / results / limitations), abstract | `## Notes` |
| `topics/<field>.md` | 12 field-index MOCs | papers grouped by listing day | `## About` + `reviewed:` |
| `objects/<source>.md` | named sources (GW170817, Sgr A*, PSR J0740+6620, …), extracted deterministically | papers mentioning the object | `## About` + `reviewed:` |
| `daily/<date>.md` | one per listing day | highlights, field index, all papers | `## Notes` |
| `weekly/<ISO week>.md` | rollup | papers per topic, highlights, objects first seen, operations log | `## Notes` |
| `Home.md`, `MAINTENANCE.md` | entry point, rules | | |

**Ownership rule.** Every note has one block between `<!-- auto:start -->` and `<!-- auto:end -->`. `wiki.py build` rewrites only that block and the frontmatter keys it owns; anything outside survives every rebuild, `created` is never touched, and a build never deletes a note. A changed note is reported and journaled, never silently overwritten.

**Provenance.** Each day's source records are stored content-addressed in `wiki/.raw/<date>.<sha12>.json`; paper notes carry `source` and `source_sha256`. Builds and lints append to `wiki/.log/operations.jsonl` (operation id, counts, changed paths).

**Cycles**

- *Daily* (`run_report.sh`): report → site → `wiki.py fold` → `wiki.py build` → `wiki.py html` → `wiki.py lint --strict`.
- *Weekly*: `fold` writes an extractive rollup; every line links to the note it came from, nothing is paraphrased.
- *Review* (`WIKI_REVIEW_DAYS`, default 90): topic/object overviews carry `reviewed: YYYY-MM-DD`; `lint` lists the ones that are overdue so curated text does not rot. New notes get one review window of grace.

**HTML export.** `python wiki.py html` renders every note to `reports/wiki/*.html` (same look as the reports, light/dark). The export is published with the site and served by the web UI at `/wiki/`. Links go both ways: each paper entry in a report has a 📖 button to its wiki note, and each wiki paper/daily note has an *Open in report* button that lands on the right day and anchor. The Markdown vault in `wiki/` stays the source of truth; the HTML is a build artifact.

**Linter** (`python wiki.py lint [--strict] [--json]`): dead wikilinks, orphans, metadata gaps per note type, stale indexes (auto block differs from a fresh dry-run build), papers whose listing day has no entry at all (abstract-only *Other topics* entries are counted separately), overdue reviews. `--strict` exits non-zero on dead links, gaps or stale indexes.

```bash
python wiki.py build --dry-run    # what would change
python wiki.py build
python wiki.py lint --strict
python wiki.py fold --week 2026-W40
python wiki.py log -n 10
```

Not ported from claude-obsidian: the SHA-256 transaction/rollback engine for multi-agent writes, Canvas views, and the claim ledger with confidence states (the digest is one source per paper, so provenance is a hash rather than a ledger).

## Development

```bash
pytest tests/        # 31 route + helper tests, < 2 s
ruff check .         # lint
ruff format .        # format in place
```

Tests cover the FastAPI shim layer (route handlers, the background `_worker`, the SSE generator). The `core/` package is exercised by the production runs that have built up `reports/`.

## Output Structure

The HTML report contains three sections:

1. **Field Index** — every paper filed under one or two labels: eight **focus topics** or twelve **index-only topics** (grouped as *Other topics*)
2. **Paper entries** — for each focus-topic paper: title, authors, method tag (`Observation` / `Simulation` / `Theory` / `Modeling`), research question, results with numbers, limitations and next steps
3. **Other topics** — a collapsed box (like *Dismissed papers*) holding title, authors, categories and abstract for every remaining paper (no LLM digest). It has its own row of topic chips to filter inside the box; clicking an index-only chip in the Field Index opens it. Each entry has a ▲ *Promote* button in the web UI

### Focus topics and index-only topics

The taxonomy lives in `core/topics.py` and is shared by the prompt, the renderer, the weekly/monthly pages and the wiki. It has two tiers:

| # | Focus topic (full digest) | Scope |
|---|---|---|
| 1 | Compact Mergers & GW *(primary interest)* | GW sources and populations, formation channels, counterparts, PTAs and SMBH binaries |
| 2 | Gamma-Ray Bursts | prompt emission, afterglows, jets and engines, progenitors, GRB-SNe |
| 3 | Extragalactic Fast X-ray Transients | Einstein Probe / XRISM / Chandra FXTs, counterparts and hosts, gamma-ray-quiet or off-axis candidates |
| 4 | Fast Radio Bursts | bursts, hosts, persistent radio sources, emission and propagation |
| 5 | Kilonovae & r-process | kilonova observations and models, r-process nucleosynthesis, kilonova spectra and remnants |
| 6 | Tidal Disruption Events | full/partial/repeating TDEs, jetted TDEs |
| 7 | Quasi-Periodic Eruptions | QPEs and their models |
| 8 | Magnetars | bursts and flares, outbursts, magnetar physics, magnetar-powered transients |

| # | Index-only topic ("Other topics": title + abstract, no digest) |
|---|---|
| 9 | Supernovae |
| 10 | FBOTs & other optical transients |
| 11 | Neutron Stars (structure / EoS / cooling) |
| 12 | Pulsars (timing, LPTs, accreting pulsars) |
| 13 | Black Holes & Accretion (XRBs, AGN accretion, IMBHs, imaging) |
| 14 | Relativistic Jets & Blazars |
| 15 | Cosmic Rays & High-energy Neutrinos |
| 16 | VHE & UHE Gamma-ray Astronomy |
| 17 | SNRs, ISM & Galaxy Clusters |
| 18 | Machine Learning & Data-driven Methods |
| 19 | Theory, Numerical Methods & Instrumentation |
| 20 | Miscellaneous |

Every paper is filed under a specific label from either tier (one, at most two), so the wiki, the summaries and search still find all related papers; only the focus tier gets the LLM digest. In the reports the index-only chips are dashed and listed after an *Other topics (index only)* divider.

Changing the tiers later: edit `FOCUS_TOPICS` / `INDEX_TOPICS` / `TOPIC_SCOPE` / `TOPIC_STYLE` in `core/topics.py`; existing reports can be re-filed without an LLM call through `core.report_post.remap_index` (keyword rules) or `file_by_keyword` for a single new label.

**👍 / 👎 feedback (web UI).** Every entry has like and dislike buttons (the cards on the Search / Similar / Recommend pages carry the same action row: star, note, similar, wiki, like, dislike; stars share the reports' browser storage, the rest hits the same server routes). 👍 on an *Other topics* entry promotes it to a full digest (one LLM call); 👍 on a focus paper marks it as liked (badge) and feeds the recommender as a positive. 👎 dismisses a paper: its entry moves to the collapsed **Dismissed papers** box at the end of the report and it no longer counts as a focus paper (★ counts, highlights, week/month/year statistics, wiki). Click the active button again to clear. The report refreshes in place after the dismiss animation (no page reload) and the tabbed site re-reads its ★ counts. Verdicts are stored server-side in `data/papers.db` (`feedback` table), so they apply to every view and survive rebuilds; the stored fragments themselves stay untouched. The header link **👍 Liked** (`/liked`) lists every liked paper with the same action row and a time filter.

**💬 personal notes (web UI).** The 💬 button opens a dialog to write a note for the paper; notes are stored server-side (`notes` table), shown under the entry and quoted in the paper's wiki note. The action row is ☆ star · 💬 note · ☍ similar · 📚 wiki · ▲ promote (index-only entries) · 👍 · 👎.

**Citation counts (NASA SciX).** With a free SciX API token (https://scixplorer.org/user/settings/token — SciX, the Science Explorer, is the successor of ADS, and ADS tokens keep working) in `SCIX_API_TOKEN` (or `~/.scix/token`), `python citations.py refresh` looks up every paper in SciX and caches its citation count in `data/papers.db` (`citations` table). The counts are decoration applied at render time, so the stored fragments stay untouched:

- every cited entry gets an amber **N citations** badge next to its arXiv id, linking to the SciX abstract page (`data-cites` on the entry);
- the week / month / year summaries gain a **Most cited** list (top 10 / 15 / 25 for the period) right after the highlights, so reviewing a period surfaces the papers the community picked up;
- wiki paper notes carry `citations:` and `scix_bibcode:` in the frontmatter plus a SciX link, and the wiki Home lists the 25 most cited papers.

`run_report.sh` (and the GitHub workflow, if the `SCIX_API_TOKEN` secret is set) run `citations.py refresh --quiet --max-requests 60` after each report: papers never looked up come first, then anything older than 7 days, 40 ids per request (the API allows 5000 requests/day). `python citations.py status` shows coverage, `python citations.py top -n 30 --since 2026-06-01` prints a ranking, `--all` forces a full refresh. Without a token everything simply renders without badges. The client talks to the SciX/ADS search API (`SCIX_API_URL` overrides the endpoint should it move away from `api.adsabs.harvard.edu`). Note that citation counts of recent preprints are naturally small; the lists become informative a few months after the listing date.

**Promoting a paper.** Anything in *Other topics* can be upgraded later to a full digest:

```bash
python promote.py 2026-09-29 2609.33364      # one LLM call for one paper; updates report, site and wiki
```

or press ▲ next to the entry in the web UI (`POST /promote/<date>/<arXiv id>`). The LLM is told to file the paper in the nearest focus topic.

### Week and month summaries

`week-<ISO week>.html`, `month-<YYYY-MM>.html` and `year-<YYYY>.html` are **summaries**, not merged copies of the daily reports: highlights, a topic × day (or topic × week) statistics table, and per-topic paper lists (collapsed for months and for *Other topics*). Every paper links to its entry in the daily report (`index.html#day/<date>/p<N>` on the static site, `/r/<date>#p<N>` in the web UI); `week.html` / `month.html` alias the latest ones and the web UI serves them at `/s/week`, `/s/month`, `/s/year`, `/s/week-2026-W40`, ….

## Notes

- arXiv does not publish new submissions on weekends; running on Saturday or Sunday will return no results
- On Mondays, the script automatically retrieves papers from the preceding Friday to account for the weekend gap
- The "Save to Craft" button is client-side only and requires the Craft desktop app on macOS; it opens a native "open Craft?" confirmation the first time each browser session

## References

- [jyangch/arxiv_report](https://github.com/jyangch/arxiv_report) — the original Chinese-language arXiv astro-ph.HE daily report generator this fork is based on (GPL-3.0).
- [AgriciDaniel/claude-obsidian](https://github.com/AgriciDaniel/claude-obsidian) — local-first Obsidian knowledge system for Claude Code; the vault layout, auto/human block ownership, content-addressed source copies, operations journal, `lint` and `fold` here follow its design.
- [karpathy/arxiv-sanity-lite](https://github.com/karpathy/arxiv-sanity-lite) — Andrej Karpathy's lightweight arXiv browser; the paper corpus, TF-IDF features, keyword search weights, "similar papers" and SVM-over-tf-idf recommendations here follow its `compute.py` / `serve.py` design (MIT).

## License

GPL-3.0. See [LICENSE](LICENSE).

## Repository layout and what is not committed

Tracked: the Python package (`core/`), the CLIs (`report.py`, `build_site.py`, `wiki.py`, `sanity.py`, `promote.py`, `citations.py`, `prefetch.py`, `manual_digest.py`), the web UI (`server.py`, `templates/`, `static/`), the shell entry points (`run_report.sh`, `run_server.sh`, `scheduler.sh`, `backfill.sh`, `phase2_runner.sh`, `env.sh`, `bin/claude`) and the GitHub workflow.

Generated or private, therefore git-ignored:

- `reports/` — the rendered site (daily reports, `fragments/` with the stored digests, week/month/year summaries, `wiki/` HTML export). On GitHub this is the `gh-pages` branch that the workflow checks out and pushes.
- `data/` — the paper corpus, feedback (👍/👎), notes and SciX citation cache (`papers.db`) plus the TF-IDF cache.
- `wiki/` — the Obsidian vault (rebuilt from `data/` + `reports/fragments/`; your reading notes live here, back it up separately).
- `env.local.sh` — host / allowed networks / tokens for one machine; API tokens otherwise come from the environment or `~/.scix/token`.
