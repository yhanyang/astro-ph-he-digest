"""Topic taxonomy shared by the prompt, the renderer, the site builder and the wiki.

Two tiers:

* :data:`FOCUS_TOPICS` -- read in depth: every paper filed here gets a full LLM digest
  (research question / methods / results / limitations). The first one is the team's
  primary interest and is preferred for the highlights.
* :data:`INDEX_TOPICS` -- the "Other topics" tier: papers are still filed under a
  specific label (so the wiki, the summaries and search can find every related paper)
  but the report shows only title, authors and abstract. Any of them can be promoted to
  a full digest later with ``promote.py`` (or the ▲ button in the web UI).

``v2_to_v3`` and ``legacy_to_new`` convert the two earlier taxonomies of older reports.
"""

import re

PRIMARY_LABEL = 'Compact Mergers & GW Multi-messenger (GW / Compact mergers)'
GRB_LABEL = 'Gamma-Ray Bursts (GRB)'

# (label used verbatim in the prompt and report index, short note name for the wiki)
FOCUS_TOPICS: list[tuple[str, str]] = [
    (PRIMARY_LABEL, 'Compact Mergers & GW'),
    (GRB_LABEL, 'Gamma-Ray Bursts'),
    ('Extragalactic Fast X-ray Transients (EFXT / FXT)', 'EFXTs'),
    ('Fast Radio Bursts (FRB)', 'Fast Radio Bursts'),
    ('Kilonovae & r-process (Kilonova)', 'Kilonovae'),
    ('Tidal Disruption Events (TDE)', 'TDEs'),
    ('Quasi-Periodic Eruptions (QPE)', 'QPEs'),
    ('Magnetars (Magnetar / SGR / AXP)', 'Magnetars'),
]
INDEX_TOPICS: list[tuple[str, str]] = [
    ('Supernovae (SNe / CCSN / SN Ia)', 'Supernovae'),
    (
        'FBOTs & Other Transients (FBOT / LFBOT / other optical transients)',
        'FBOTs & other transients',
    ),
    ('Neutron Stars (NS structure / EoS / cooling)', 'Neutron Stars'),
    ('Pulsars (Pulsar / Timing / LPT)', 'Pulsars'),
    ('Black Holes & Accretion (BH / XRB / AGN accretion / IMBH)', 'Black Holes & Accretion'),
    ('Relativistic Jets & Blazars (Jets / Blazar / Microquasar)', 'Relativistic Jets & Blazars'),
    ('Cosmic Rays & High-energy Neutrinos (UHECR / Galactic CR / HE ν)', 'Cosmic Rays & Neutrinos'),
    ('VHE & UHE Gamma-ray Astronomy (VHE / UHE γ-ray / PWN)', 'VHE & UHE Gamma-rays'),
    ('SNRs, ISM & Galaxy Clusters (SNR / ISM / ICM)', 'SNRs, ISM & Clusters'),
    ('Machine Learning & Data-driven Methods (ML / AI)', 'Machine Learning'),
    (
        'Theory, Numerical Methods & Instrumentation (Theory / Numerical / Instrumentation)',
        'Theory, Methods & Instrumentation',
    ),
    ('Miscellaneous (other)', 'Miscellaneous'),
]
OTHER_GROUP = 'Other topics'  # display name of the index-only tier
OTHER_LABEL = 'Miscellaneous (other)'  # catch-all label inside that tier
OTHER_NAME = 'Miscellaneous'

TOPICS: list[tuple[str, str]] = [*FOCUS_TOPICS, *INDEX_TOPICS]
TOPIC_NAME: dict[str, str] = {label: name for label, name in TOPICS}
FOCUS_LABELS: frozenset[str] = frozenset(label for label, _ in FOCUS_TOPICS)
INDEX_LABELS: frozenset[str] = frozenset(label for label, _ in INDEX_TOPICS)

# Guidance rendered into the prompt, one line per category.
TOPIC_SCOPE: dict[str, str] = {
    PRIMARY_LABEL: (
        'gravitational-wave sources and populations, binary black hole / neutron star mergers and '
        'their formation channels, GW counterparts and multi-messenger follow-up, PTA backgrounds and '
        'SMBH binaries, GW data analysis and waveforms'
    ),
    GRB_LABEL: (
        'every paper whose main subject is gamma-ray bursts: prompt emission, afterglows, jets and '
        'central engines (including collapsar jet breakout), progenitors and hosts, GRB-associated '
        'supernovae, polarimetry, GRB cosmology (fast X-ray transients with a detected gamma-ray counterpart)'
    ),
    'Extragalactic Fast X-ray Transients (EFXT / FXT)': (
        'extragalactic fast X-ray transients: Einstein Probe / XRISM / Chandra / Swift FXTs and their '
        'counterparts and hosts, gamma-ray-quiet or off-axis / choked-jet candidates, shock breakouts, '
        'FXT populations and rates, X-ray flashes without a GRB trigger (GRB-triggered events stay in GRB)'
    ),
    'Fast Radio Bursts (FRB)': (
        'FRB observations, localisations, hosts, persistent radio sources, emission mechanisms, '
        'propagation effects (scintillation, plasma lensing), and FRBs as cosmological probes'
    ),
    'Kilonovae & r-process (Kilonova)': (
        'kilonova observations and models, r-process nucleosynthesis in mergers, kilonova spectra and '
        'atomic data, kilonova remnants, GRB-associated kilonovae (file also under GRB when relevant)'
    ),
    'Tidal Disruption Events (TDE)': (
        'full and partial tidal disruptions, repeating TDEs, TDE demographics, jetted TDEs, '
        'nuclear transients interpreted as TDEs'
    ),
    'Quasi-Periodic Eruptions (QPE)': (
        'quasi-periodic eruptions from galactic nuclei and their models (EMRI-disk collisions, '
        'disk instabilities), including QPE-TDE connections'
    ),
    'Magnetars (Magnetar / SGR / AXP)': (
        'magnetars and soft gamma repeaters: bursts and giant flares, outbursts, magnetar emission '
        'and field physics, magnetar-powered transients, magnetar-FRB connections'
    ),
    'Supernovae (SNe / CCSN / SN Ia)': 'supernovae of all types, progenitors, explosion mechanism, SN light curves and spectra, SN rates',
    'FBOTs & Other Transients (FBOT / LFBOT / other optical transients)': 'fast blue optical transients, novae, luminous red novae and other optical transients that are not SNe, TDEs or kilonovae',
    'Neutron Stars (NS structure / EoS / cooling)': 'neutron-star structure, equation of state, masses and radii, cooling, crusts and interiors',
    'Pulsars (Pulsar / Timing / LPT)': 'radio and X-ray pulsars, timing and glitches, pulsar emission, long-period radio transients, accreting X-ray pulsars',
    'Black Holes & Accretion (BH / XRB / AGN accretion / IMBH)': 'black hole accretion at any mass: X-ray binaries and ULXs, AGN accretion and variability, changing-look AGN, IMBHs, horizon-scale imaging',
    'Relativistic Jets & Blazars (Jets / Blazar / Microquasar)': 'jet launching and propagation, blazars and radio galaxies, jet polarization, microquasar jets, discrete ejections',
    'Cosmic Rays & High-energy Neutrinos (UHECR / Galactic CR / HE ν)': 'cosmic-ray spectra, composition and transport, UHECR sources, high-energy neutrino astronomy',
    'VHE & UHE Gamma-ray Astronomy (VHE / UHE γ-ray / PWN)': 'TeV-PeV gamma-ray sources and surveys, PWNe, Galactic Center emission, gamma-ray dark matter searches (non-GRB)',
    'SNRs, ISM & Galaxy Clusters (SNR / ISM / ICM)': 'supernova remnants, interstellar medium, galaxy clusters and the intracluster medium',
    'Machine Learning & Data-driven Methods (ML / AI)': 'machine learning and AI applied to high-energy astrophysics: neural networks, simulation-based inference, normalizing flows, classifiers and anomaly detection for transients, LLM-based tools (file also under the science topic when the application dominates)',
    'Theory, Numerical Methods & Instrumentation (Theory / Numerical / Instrumentation)': 'papers whose main contribution is a method, code, detector, mission concept, catalog or purely theoretical formalism',
    OTHER_LABEL: 'anything that fits none of the above (solar and stellar physics, exoplanets, pure particle physics, ...)',
}

# --------------------------------------------------------------------------- display
# Abbreviation and colour class for the Field Index chips (reports, summaries, site).
TOPIC_STYLE: dict[str, tuple[str, str]] = {
    PRIMARY_LABEL: ('GW', 'fc-gw'),
    GRB_LABEL: ('GRB', 'fc-grb'),
    'Extragalactic Fast X-ray Transients (EFXT / FXT)': ('EFXT', 'fc-efxt'),
    'Fast Radio Bursts (FRB)': ('FRB', 'fc-frb'),
    'Kilonovae & r-process (Kilonova)': ('KN', 'fc-kn'),
    'Tidal Disruption Events (TDE)': ('TDE', 'fc-tde'),
    'Quasi-Periodic Eruptions (QPE)': ('QPE', 'fc-qpe'),
    'Magnetars (Magnetar / SGR / AXP)': ('MAG', 'fc-mag'),
    'Supernovae (SNe / CCSN / SN Ia)': ('SNe', 'fc-sne'),
    'FBOTs & Other Transients (FBOT / LFBOT / other optical transients)': ('FBOT', 'fc-fbot'),
    'Neutron Stars (NS structure / EoS / cooling)': ('NS', 'fc-ns'),
    'Pulsars (Pulsar / Timing / LPT)': ('PSR', 'fc-psr'),
    'Black Holes & Accretion (BH / XRB / AGN accretion / IMBH)': ('BH', 'fc-bh'),
    'Relativistic Jets & Blazars (Jets / Blazar / Microquasar)': ('Jets', 'fc-jets'),
    'Cosmic Rays & High-energy Neutrinos (UHECR / Galactic CR / HE ν)': ('CR', 'fc-cr'),
    'VHE & UHE Gamma-ray Astronomy (VHE / UHE γ-ray / PWN)': ('VHE', 'fc-vhe'),
    'SNRs, ISM & Galaxy Clusters (SNR / ISM / ICM)': ('SNR', 'fc-snr'),
    'Machine Learning & Data-driven Methods (ML / AI)': ('ML', 'fc-ml'),
    'Theory, Numerical Methods & Instrumentation (Theory / Numerical / Instrumentation)': (
        'Theory',
        'fc-theory',
    ),
    OTHER_LABEL: ('Misc', 'fc-other'),
}


def topic_abbr(label: str) -> str:
    return TOPIC_STYLE.get(label, (label.split(' (')[0][:8], ''))[0]


def topic_class(label: str) -> str:
    cls = TOPIC_STYLE.get(label, ('', 'fc-other'))[1]
    return cls if label in FOCUS_LABELS else f'{cls} chip-nf'


def topic_style_json() -> str:
    import json

    return json.dumps(
        {
            label: {'abbr': abbr, 'cls': cls, 'focus': label in FOCUS_LABELS}
            for label, (abbr, cls) in TOPIC_STYLE.items()
        },
        ensure_ascii=False,
    ).replace('</', '<\\/')


# Shared CSS for the coloured chips (light + dark). Plain CSS, safe to drop into any page.
CHIP_CSS = """
.chip { display:inline-flex; align-items:center; gap:6px; padding:3px 11px; border-radius:20px; font-size:.78rem;
        font-weight:600; border:1px solid transparent; font-family:inherit; line-height:1.4; white-space:nowrap;
        text-decoration:none; }
button.chip { cursor:pointer; } button.chip:hover { filter:brightness(.96); }
.chip .chip-n { font-weight:500; opacity:.75; font-size:.9em; }
.chip.is-active { outline:2px solid currentColor; outline-offset:1px; }
.chip.chip-sm { padding:1px 8px; font-size:.7rem; gap:4px; }
.chip.chip-nf { border-style:dashed; opacity:.82; font-weight:500; }
.chip-divider { font-size:.72rem; color:#6b7280; align-self:center; margin:0 2px 0 8px; white-space:nowrap; }
.chip.fc-all { background:#eef2ff; color:#3730a3; border-color:#a5b4fc; }
.fc-gw   { background:#ccfbf1; color:#115e59; border-color:#5eead4; }
.fc-grb  { background:#ffedd5; color:#9a3412; border-color:#fb923c; }
.fc-efxt { background:#fef9c3; color:#854d0e; border-color:#fde047; }
.fc-frb  { background:#dbeafe; color:#1e40af; border-color:#93c5fd; }
.fc-kn   { background:#fce7f3; color:#9d174d; border-color:#f9a8d4; }
.fc-tde  { background:#fff1f2; color:#881337; border-color:#fda4af; }
.fc-qpe  { background:#fdf2f8; color:#701a75; border-color:#f0abfc; }
.fc-mag  { background:#ede9fe; color:#5b21b6; border-color:#c4b5fd; }
.fc-sne  { background:#fdf4ff; color:#86198f; border-color:#e9d5ff; }
.fc-fbot { background:#f0f9ff; color:#075985; border-color:#bae6fd; }
.fc-ns   { background:#f5f3ff; color:#4c1d95; border-color:#ddd6fe; }
.fc-psr  { background:#eef2ff; color:#3730a3; border-color:#c7d2fe; }
.fc-bh   { background:#fee2e2; color:#991b1b; border-color:#fca5a5; }
.fc-jets { background:#fff7ed; color:#9a3412; border-color:#fed7aa; }
.fc-cr   { background:#f0fdf4; color:#166534; border-color:#bbf7d0; }
.fc-vhe  { background:#f7fee7; color:#3f6212; border-color:#d9f99d; }
.fc-snr  { background:#ecfeff; color:#155e75; border-color:#a5f3fc; }
.fc-ml   { background:#eef2ff; color:#4338ca; border-color:#c7d2fe; }
.fc-theory { background:#f8fafc; color:#334155; border-color:#cbd5e1; }
.fc-other { background:#f1f5f9; color:#475569; border-color:#cbd5e1; }
@media (prefers-color-scheme: dark) {
  .chip-divider { color:#94a3b8; }
  .chip.fc-all { background:#1e1b4b; color:#c7d2fe; border-color:#4338ca; }
  .fc-gw   { background:#042f2e; color:#5eead4; border-color:#115e59; }
  .fc-grb  { background:#431407; color:#fdba74; border-color:#c2410c; }
  .fc-efxt { background:#422006; color:#fde047; border-color:#854d0e; }
  .fc-frb  { background:#1e3a5f; color:#93c5fd; border-color:#1e40af; }
  .fc-kn   { background:#500724; color:#f9a8d4; border-color:#9d174d; }
  .fc-tde  { background:#4c0519; color:#fda4af; border-color:#881337; }
  .fc-qpe  { background:#4a044e; color:#f0abfc; border-color:#701a75; }
  .fc-mag  { background:#2e1065; color:#c4b5fd; border-color:#4c1d95; }
  .fc-sne  { background:#3b0764; color:#e9d5ff; border-color:#6b21a8; }
  .fc-fbot { background:#082f49; color:#bae6fd; border-color:#075985; }
  .fc-ns   { background:#2e1065; color:#ddd6fe; border-color:#5b21b6; }
  .fc-psr  { background:#1e1b4b; color:#c7d2fe; border-color:#3730a3; }
  .fc-bh   { background:#450a0a; color:#fca5a5; border-color:#991b1b; }
  .fc-jets { background:#431407; color:#fed7aa; border-color:#9a3412; }
  .fc-cr   { background:#052e16; color:#bbf7d0; border-color:#166534; }
  .fc-vhe  { background:#1a2e05; color:#d9f99d; border-color:#3f6212; }
  .fc-snr  { background:#083344; color:#a5f3fc; border-color:#155e75; }
  .fc-ml   { background:#1e1b4b; color:#c7d2fe; border-color:#4338ca; }
  .fc-theory { background:#1e293b; color:#cbd5e1; border-color:#334155; }
  .fc-other { background:#1e293b; color:#94a3b8; border-color:#334155; }
}
"""

# --------------------------------------------------------------------------- conversions
_KN_RE = re.compile(r'kilonova|macronova|r-process|\br\$?-?process|lanthanide|AT ?2017gfo', re.I)
_FBOT_RE = re.compile(
    r'\bL?FBOTs?\b|fast blue optical|AT ?2018cow|luminous fast|\bnova\b|novae\b', re.I
)
_MAG_RE = re.compile(r'magnetar|soft gamma[- ]repeater|\bSGRs?\b|\bAXPs?\b|giant flare', re.I)
_PSR_RE = re.compile(
    r'pulsar|\bPSR\b|glitch|long[- ]period (?:radio )?transient|\bLPTs?\b|timing array|\bPTA\b',
    re.I,
)
_JET_RE = re.compile(
    r'\bjets?\b|blazar|BL ?Lac|FSRQ|microquasar|EVPA|polari[sz]ation angle|radio galax|superluminal',
    re.I,
)
_CR_RE = re.compile(
    r'cosmic[- ]ray|\bUHECR|\bCRs\b|high-energy neutrino|IceCube|KM3NeT|neutrino (?:flux|source|emission|astronomy)',
    re.I,
)
_VHE_RE = re.compile(
    r'\bTeV\b|\bPeV\b|\bVHE\b|\bUHE\b|H\.E\.S\.S|HESS J|LHAASO|HAWC|Cherenkov|Fermi-LAT|Fermi LAT|\bLAT\b|pulsar wind nebula|\bPWN|gamma-ray (?:source|emission|sky|excess|line)',
    re.I,
)
_SNR_RE = re.compile(
    r'supernova remnant|\bSNRs?\b|interstellar medium|\bISM\b|galaxy cluster|intracluster|\bICM\b|molecular cloud|H ?II region',
    re.I,
)
_BH_RE = re.compile(
    r'black hole|\bBHs?\b|AGN|active galactic|quasar|Seyfert|changing[- ]look|X-ray binar|\bXRBs?\b|\bULXs?\b|accret|Sgr A|M87|\bIMBH',
    re.I,
)
_SN_RE = re.compile(
    r'supernova|\bSNe?\b|\bSN ?[12]\d{3}|core[- ]collapse|Type (?:Ia|Ib|Ic|II)', re.I
)
_NS_RE = re.compile(
    r'neutron star|\bNSs?\b|equation of state|\bEoS\b|dense matter|quark star|strange star', re.I
)
_ML_RE = re.compile(
    r'machine[- ]learning|deep[- ]learning|neural network|\btransformer|normali[sz]ing flow|simulation-based inference|'
    r'autoencoder|convolutional|random forest|gradient boosting|reinforcement learning|large language model|\bLLMs?\b|'
    r'foundation model|self-supervised|\bGANs?\b|diffusion model|anomaly detection|\bclassifier\b',
    re.I,
)
_THEORY_RE = re.compile(
    r'instrument|telescope|detector|mission|observatory|pipeline|catalog|survey|code\b|algorithm|machine learning|neural|simulation code|framework|method',
    re.I,
)


_EFXT_EXCLUDE_RE_SAFE = re.compile(r'\bSFXTs?\b|supergiant fast[- ]x-?ray', re.I)  # Galactic HMXBs


def _index_topic_for(text: str) -> str:
    """Most specific index-only label for a paper that is not in any focus topic."""
    for regex, label in (
        (_CR_RE, 'Cosmic Rays & High-energy Neutrinos (UHECR / Galactic CR / HE ν)'),
        (_VHE_RE, 'VHE & UHE Gamma-ray Astronomy (VHE / UHE γ-ray / PWN)'),
        (_SNR_RE, 'SNRs, ISM & Galaxy Clusters (SNR / ISM / ICM)'),
        (_JET_RE, 'Relativistic Jets & Blazars (Jets / Blazar / Microquasar)'),
        (_BH_RE, 'Black Holes & Accretion (BH / XRB / AGN accretion / IMBH)'),
        (_PSR_RE, 'Pulsars (Pulsar / Timing / LPT)'),
        (_NS_RE, 'Neutron Stars (NS structure / EoS / cooling)'),
        (_SN_RE, 'Supernovae (SNe / CCSN / SN Ia)'),
        (_FBOT_RE, 'FBOTs & Other Transients (FBOT / LFBOT / other optical transients)'),
        (_ML_RE, 'Machine Learning & Data-driven Methods (ML / AI)'),
        (
            _THEORY_RE,
            'Theory, Numerical Methods & Instrumentation (Theory / Numerical / Instrumentation)',
        ),
    ):
        if regex.search(text):
            return label
    return OTHER_LABEL


def v2_to_v3(old_label: str, text: str) -> list[str]:
    """Map one label of the previous taxonomy (8 focus + Other) to the current one.

    Combined categories are split by keywords in the paper's title + abstract; the
    former catch-all is re-filed under the most specific index-only label.
    """
    if old_label in TOPIC_NAME:
        return [old_label]
    if old_label.startswith('Supernovae, Kilonovae'):
        out = []
        if _KN_RE.search(text):
            out.append('Kilonovae & r-process (Kilonova)')
        if _FBOT_RE.search(text) and not _SN_RE.search(text):
            out.append('FBOTs & Other Transients (FBOT / LFBOT / other optical transients)')
        return out or ['Supernovae (SNe / CCSN / SN Ia)']
    if old_label.startswith('Neutron Stars, Pulsars'):
        if _MAG_RE.search(text):
            return ['Magnetars (Magnetar / SGR / AXP)']
        if _PSR_RE.search(text) and not _NS_RE.search(text):
            return ['Pulsars (Pulsar / Timing / LPT)']
        if _PSR_RE.search(text):
            return [
                'Pulsars (Pulsar / Timing / LPT)',
                'Neutron Stars (NS structure / EoS / cooling)',
            ]
        return ['Neutron Stars (NS structure / EoS / cooling)']
    if old_label.startswith('Black Holes & Relativistic Jets'):
        if _JET_RE.search(text):
            return ['Relativistic Jets & Blazars (Jets / Blazar / Microquasar)']
        return ['Black Holes & Accretion (BH / XRB / AGN accretion / IMBH)']
    if old_label == 'Other topics':
        return [_index_topic_for(text)]
    return [OTHER_LABEL]


# Former 12-category labels (first taxonomy) -> current labels; None = decide by keyword.
LEGACY_MAP: dict[str, str | None] = {
    'Gamma-Ray Bursts (GRB)': GRB_LABEL,
    'Fast Radio Bursts (FRB)': 'Fast Radio Bursts (FRB)',
    'Supernovae, Kilonovae & Transients (SNe / Kilonova / TDE / FBOT)': None,
    'AGN & Blazars (AGN / Blazar / Quasar)': None,
    'Neutron Stars, Pulsars & Magnetars (NS / Pulsar / Magnetar)': None,
    'Compact Mergers & GW Multi-messenger (GW / Compact mergers)': PRIMARY_LABEL,
    'X-ray Binaries & Accretion (XRB / Accretion / Disk-Jet)': None,
    'Black Holes & Relativistic Jets (BH / Jets / SMBH)': None,
    'Cosmic Rays & High-energy Neutrinos (UHECR / Galactic CR / HE ν)': 'Cosmic Rays & High-energy Neutrinos (UHECR / Galactic CR / HE ν)',
    'VHE & UHE Gamma-ray Astronomy (VHE / UHE γ-ray)': 'VHE & UHE Gamma-ray Astronomy (VHE / UHE γ-ray / PWN)',
    'SNRs, ISM & Galaxy Clusters (SNR / ISM / ICM)': 'SNRs, ISM & Galaxy Clusters (SNR / ISM / ICM)',
    'Theory, Numerical Methods & Instrumentation (Theory / Numerical / Instrumentation)': 'Theory, Numerical Methods & Instrumentation (Theory / Numerical / Instrumentation)',
}
_TDE_RE = re.compile(r'tidal[- ]disruption|\bTDEs?\b', re.I)
_QPE_RE = re.compile(r'quasi[- ]periodic eruption|\bQPEs?\b', re.I)


def legacy_to_new(old_label: str, text: str) -> list[str]:
    """Map one label of the original 12-category taxonomy to the current one."""
    target = LEGACY_MAP.get(old_label, OTHER_LABEL)
    if target is not None:
        return [target]
    if old_label.startswith('Supernovae'):
        out = []
        if _TDE_RE.search(text):
            out.append('Tidal Disruption Events (TDE)')
        if _QPE_RE.search(text):
            out.append('Quasi-Periodic Eruptions (QPE)')
        if _KN_RE.search(text):
            out.append('Kilonovae & r-process (Kilonova)')
        return out or ['Supernovae (SNe / CCSN / SN Ia)']
    if old_label.startswith('Neutron Stars'):
        return v2_to_v3('Neutron Stars, Pulsars & Magnetars (NS / Pulsar / Magnetar)', text)
    if _JET_RE.search(text):
        return ['Relativistic Jets & Blazars (Jets / Blazar / Microquasar)']
    return ['Black Holes & Accretion (BH / XRB / AGN accretion / IMBH)']


index_topic_for = _index_topic_for  # public alias
