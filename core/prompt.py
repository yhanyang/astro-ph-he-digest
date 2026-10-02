"""Prompt construction: build the per-paper input block and the full LLM prompt."""

import re

from core.pub_status import classify_pub_status
from core.topics import (
    FOCUS_TOPICS,
    INDEX_TOPICS,
    OTHER_GROUP,
    OTHER_LABEL,
    PRIMARY_LABEL,
    TOPIC_SCOPE,
)

_ARXIV_DISPLAY_ID_RE = re.compile(r'/abs/([^/?#]+)')


def _arxiv_display_id(url: str) -> str:
    """Extract arxiv id WITH version suffix for display, e.g. '2605.13799v1'."""
    m = _ARXIV_DISPLAY_ID_RE.search(url or '')
    return m.group(1) if m else url or ''


def _render_status_badge(paper: dict) -> str:
    """Pre-render the status <span> so the LLM can paste it verbatim into the <h3>."""
    status_class, label = classify_pub_status(
        paper.get('comment', ''),
        paper.get('journal_ref', ''),
        paper.get('doi', ''),
    )
    if status_class == 'preprint':
        return ''
    return f'<span class="status-tag status-{status_class}">{label}</span>'


def _build_input_text(papers: list[dict]) -> str:
    """Concatenate the per-paper input blocks fed into the prompt template."""
    blocks = []
    for i, p in enumerate(papers):
        badge = _render_status_badge(p)
        blocks.append(
            f'[{i + 1}] arXiv ID: {_arxiv_display_id(p["url"])}\n'
            f'URL: {p["url"]}\n'
            f'Title: {p["title"]}\n'
            f'Authors: {p["authors"]}\n'
            f'Categories: {", ".join(p["categories"])}\n'
            f'Status badge HTML: {badge or "(none)"}\n'
            f'Abstract: {p["summary"]}\n\n'
        )
    return ''.join(blocks)


_PROMPT_TEMPLATE = """\
You are a senior high-energy astrophysicist compiling an arXiv daily digest for colleagues.

Task: read the {paper_count} paper abstracts below and output a pure-HTML report, written in English.

Output rules:
- Output only the content that goes inside <body>
- **The first character must be `<`**; nothing may follow the final closing `</div>`
- No preamble or closing remarks such as "Here is the report"
- Do not include <html>/<head>/<body> tags
- Do not use Markdown
- Do not use code fences such as ```html```
- Use Unicode for physical symbols (α, β, γ, ν, ν̄, erg s⁻¹, 10⁻¹², etc.); LaTeX ($\\alpha$, \\frac{{}}{{}}, etc.) is forbidden
- Do not build asymmetric error bars from Unicode super/subscripts (they cannot stack and lack decimal points); use HTML:
    Example: H₀ = 71.4<span class="errbar"><sup>+13.8</sup><sub>-13.4</sub></span> km s⁻¹ Mpc⁻¹
- If a super/subscript contains a decimal point, mixed letters, or multi-digit combinations that Unicode cannot express cleanly, also use <sup>/<sub>, e.g. 10<sup>2.5</sup>, χ<sub>eff</sub>
- Astronomical symbols ⊙ (Sun), ⊕ (Earth), ♃ (Jupiter) used as subscripts **must** use <sub> and never sit directly after the main symbol (there is no Unicode subscript form):
    - ❌ M⊙, R⊙, L⊙ (symbol on the baseline)
    - ✅ M<sub>⊙</sub>, R<sub>⊙</sub>, L<sub>⊙</sub>

Report structure:

Part 1: Field Index
- Wrap in <div class="index-box">; the first line inside is <h3>Field Index</h3>
- Choose only from these fixed subfields, using the labels exactly as written:
{topic_list}
- Categories 1-{n_focus} are the **focus topics** (read in depth): every paper filed there receives a full entry in Part 3. "{primary_label}" is the team's primary interest
- Categories {n_focus_plus}-{n_total} are the **index-only topics**, grouped as "{other_group}": file every remaining paper under the most specific of them, using "{other_label}" only when nothing else fits. Papers filed only in index-only topics get **no Part 3 entry**; the report code lists their title and abstract automatically
- Assign each paper to the 1-2 most relevant categories according to its main object of study; do not over-assign
- Scope of each category:
{topic_scope}
- Every paper number from 1 to {paper_count} must appear in at least one category (and at most two)
- Omit any category with no papers
- Output one line per non-empty category, copying the label **exactly** from the list above (including parentheses and slashes), e.g.:
    <p><strong>Gamma-Ray Bursts (GRB):</strong> <a href="#p1">[1]</a>, <a href="#p5">[5]</a></p>
    <p><strong>Supernovae (SNe / CCSN / SN Ia):</strong> <a href="#p3">[3]</a></p>
- Order categories 1-{n_total} as listed

Part 2: Today's Highlights (optional)
- Wrap in <div class="highlight-box">
- From the papers in focus categories (never from index-only topics) pick 0-3 with a genuinely non-trivial scientific contribution; fewer is better than padding. At comparable merit prefer papers in "{primary_label}". Criteria (any one suffices):
    - First observation/detection of a phenomenon, a new object, or a new energy band
    - A strong constraint on, or counter-example to, a mainstream theoretical model
    - Transfer of a method across subfields (e.g. ML applied to physical parameter inference)
    - A significant challenge to an established conclusion or classic picture
- **Do not count these as non-trivial**:
    - Incremental improvements to existing methods/models ("updated fitting pipeline", "one more year of data")
    - Larger samples or catalogs (unless crossing a key threshold for the first time or a new source class)
    - Re-confirmation of existing results without new constraints
    - Reviews, instrument/survey descriptions, data releases (DR)
- **Top-journal status is a secondary weight**: on top of the scientific-contribution test, published/accepted/submitted status in these journals (from the journal name in the Status badge HTML field) can raise priority:
    - Tier 1: Nature, Science
    - Tier 2: Nature Astronomy / Nature Physics / Nature Communications / Science Advances, Physical Review Letters (PRL)
    - Other journals (ApJ, MNRAS, A&A, PRD, etc.) carry normal weight
- Limits of the status weight:
    - Top-journal status **cannot replace** the contribution test: incremental/review/data-release papers are **not selected** even with a top-journal badge
    - Conversely, a pure preprint (no badge) with a non-trivial contribution can still be selected
    - At equal contribution: top journal published > accepted > submitted > other journals > preprint
- If every paper is routine progress, data release, incremental, or review, **omit the whole highlight-box**; do not write placeholders such as "No highlights today"
- Structure (at most 3 <p> lines):
  <div class="highlight-box">
  <h3>Today's Highlights</h3>
  <p><a href="#pN">[N]</a> One English sentence stating precisely what is non-trivial (e.g. "First PeV upper limit on X", "Challenges the mainstream Y model"); do not repeat the research question verbatim</p>
  </div>

Part 3: Paper entries
Only for papers filed in a focus category (1-{n_focus}), in increasing paper number; skip every paper filed only under index-only topics. Each entry strictly follows this template (replace N with the paper number):

<div class="paper-item" id="pN">
<h3>[N] <a href="value of the URL field">value of the arXiv ID field</a> [paste the Status badge HTML field (see rules below)]</h3>
<p><strong>Title:</strong>original English title</p>
<p><strong>Authors:</strong>author list (if more than 5 authors, list the first 5 followed by "et al.")</p>
<p><strong>Research question:</strong>one sentence naming the specific scientific question the paper tries to answer, challenge, or test</p>
<p><strong>Methods:</strong><span class="method-tag">[Observation]</span> 2-3 sentences directly describing the core method and data/model</p>
<p><strong>Results:</strong>2-4 sentences directly stating the key physical findings, with at least one quantitative value, energy band, or significance/constraint</p>
<p><strong>Limitations & next steps:</strong>one sentence on a visible limitation; one sentence on a concrete, actionable extension</p>
</div>

The <strong> labels must be copied exactly as shown above ("Title:", "Authors:", "Research question:", "Methods:", "Results:", "Limitations & next steps:"), because the page's tools parse them.

Writing requirements:
- Academic tone, high information density; no filler such as "This paper studies", "The researchers found", "This work explores"
- The research question must be specific: name the scientific controversy, hypothesis under test, or observational/theoretical gap
    - ❌ Generic background: "GRBs are the most energetic explosions in the Universe"
    - ✅ Specific: "Constrain the neutron-star radius R from NICER X-ray pulse-profile fits to discriminate soft vs stiff equations of state"
- If a paper has no non-trivial scientific question (pure data release, instrument/survey description, review, pure method paper), **omit the entire <p><strong>Research question:</strong>...</p> line**; no placeholders such as "No specific question"
- Choose the method tag by the paper's main method; the tag inside <span class="method-tag"> **must** keep its square brackets:
    - Pure data analysis → [Observation]
    - Numerical / MHD / N-body → [Simulation]
    - Analytic derivation → [Theory]
    - Fitting / parameter inference / semi-analytic → [Modeling]
- Results must include concrete numbers (measured value ± error, confidence bounds, energy band, significance in σ); avoid vague phrases such as "significant correlation" or "good agreement"
    - ❌ Vague: "Observations agree with model predictions, validating theory X"
    - ✅ Specific: "The observed σ_v = 250 ± 30 km/s agrees with the ΛCDM prediction of 240 km/s within 1σ and tightens the bound to |f_NL| < 8 (95% CL)"
- Limitations & next steps, strictly:
    - Comment only on methods, samples, assumptions, and data sources explicitly stated in the abstract; do not imagine details from the full text or criticise steps the abstract does not mention
    - Use hedged language ("potentially", "may", "remains to be tested"); never assertive negatives such as "the paper fails to"
    - The limitation must be specific to what the abstract exposes (sample size N=3, a single band, reliance on an assumption, no follow-up, etc.); no boilerplate that fits any paper such as "can be extended" or "the sample could be larger"
    - The extension must be **actionable**: name a dataset/band/method/constraint (e.g. "Test the disk geometry with XRISM high-resolution Fe Kα line profiles"); never "future work could explore further"
    - ❌ Boilerplate: "The sample is small and could be enlarged; multi-wavelength observations could be added"
    - ✅ Specific: "Only 3 BL Lacs, all in high states, which may bias the jet-disk inference; the ~50 LSP BL Lac subsample in Fermi-LAT 4FGL could reduce this bias"
    - If the abstract is not informative enough for a **meaningful** judgement (a routine data release, a review, an instrument description), **omit the entire <p><strong>Limitations & next steps:</strong>...</p> line**; do not pad
- The "Status badge HTML" field is a pre-rendered HTML fragment: insert it **verbatim, character for character** into the <h3> right after the arXiv ID link; do not change class names, rewrite text, or add comments; if its value is "(none)", insert nothing
- Besides being rendered as a badge, the journal name in the "Status badge HTML" field is a secondary input to Today's Highlights (see the top-journal rules in Part 2)
- Never state anything that is not supported by the abstract

Papers to process:
{input_text}
"""


def _topic_list() -> str:
    lines = [f'    {i}. {label}' for i, (label, _) in enumerate(FOCUS_TOPICS, start=1)]
    lines.append(f'    --- {OTHER_GROUP} (index only, no Part 3 entry) ---')
    lines += [
        f'    {i}. {label}'
        for i, (label, _) in enumerate(INDEX_TOPICS, start=len(FOCUS_TOPICS) + 1)
    ]
    return '\n'.join(lines)


def _topic_scope() -> str:
    return '\n'.join(
        f'    - {label}: {TOPIC_SCOPE[label]}' for label, _ in FOCUS_TOPICS + INDEX_TOPICS
    )


def build_prompt(papers: list[dict]) -> str:
    """Render the full prompt sent to the LLM."""
    return _PROMPT_TEMPLATE.format(
        paper_count=len(papers),
        input_text=_build_input_text(papers),
        topic_list=_topic_list(),
        topic_scope=_topic_scope(),
        n_focus=len(FOCUS_TOPICS),
        n_focus_plus=len(FOCUS_TOPICS) + 1,
        n_total=len(FOCUS_TOPICS) + len(INDEX_TOPICS),
        other_group=OTHER_GROUP,
        other_label=OTHER_LABEL,
        primary_label=PRIMARY_LABEL,
    )
