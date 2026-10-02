"""Provider keys, model defaults, and dispatch order.

All values come from environment variables; defaults are baked in for offline runs
(though API keys must be supplied -- an empty key disables the provider).
"""

import os

PREFERRED_PROVIDER = os.getenv('PREFERRED_PROVIDER', 'openai')  # 'claude' | 'gemini' | 'openai'
FALLBACK_ORDER = tuple(
    p.strip() for p in os.getenv('FALLBACK_ORDER', 'openai').split(',') if p.strip()
)

CLAUDE_BACKEND = os.getenv('CLAUDE_BACKEND', 'cli')
CLAUDE_API_KEY = os.getenv('CLAUDE_API_KEY', '')
CLAUDE_MODEL = os.getenv('CLAUDE_MODEL', 'claude-opus-4-6')

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')
GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-3.1-flash-lite-preview')

OPENAI_BACKEND = os.getenv('OPENAI_BACKEND', 'codex')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')
OPENAI_MODEL = os.getenv('OPENAI_MODEL', 'gpt-5.5')
CODEX_CLI = os.getenv('CODEX_CLI', '')

# Optional Craft integration; leave empty to hide the "Save to Craft" buttons.
CRAFT_SPACE_ID = os.getenv('CRAFT_SPACE_ID', '')
CRAFT_ARXIV_FOLDER_ID = os.getenv('CRAFT_ARXIV_FOLDER_ID', '')

# Optional team / project name shown next to the site title (static site, reports, web UI). Empty = personal use.
SITE_TEAM = os.getenv('SITE_TEAM', '')
