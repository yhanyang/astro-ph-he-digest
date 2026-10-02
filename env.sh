# Shared environment for run_report.sh / run_server.sh. Edit here, not in the scripts.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PATH="$HERE/bin:$PATH"            # provides the `claude` command
export PREFERRED_PROVIDER=claude
export FALLBACK_ORDER=claude
export CLAUDE_BACKEND=cli                # uses the logged-in Claude Code account
# A nested Claude Code session must not look like one to the child CLI.
unset CLAUDECODE CLAUDE_CODE_ENTRYPOINT
PY="$HERE/.venv/bin/python"
# Content directory (reports, fragments, summaries, wiki export, .data, .wiki); its own git repo.
export REPORTS_DIR="${REPORTS_DIR:-astro-ph-reports}"
# NASA SciX token for citation counts (https://scixplorer.org/user/settings/token; ADS tokens work too).
# export SCIX_API_TOKEN=...           # or put it in ~/.scix/token

# Web UI network access (defaults: this machine only). To open the UI to your lab network put
# HOST / ALLOWED_NETS / UI_TOKEN into env.local.sh (git-ignored), e.g.
#   export HOST=0.0.0.0
#   export ALLOWED_NETS="127.0.0.1/32,::1/128,10.0.0.0/8"   # CIDRs that may connect
#   export UI_TOKEN=change-me                                 # optional write gate (/unlock?token=)
export HOST="${HOST:-127.0.0.1}"
export ALLOWED_NETS="${ALLOWED_NETS:-127.0.0.1/32,::1/128}"

# Machine-specific overrides (not committed).
if [ -f "$HERE/env.local.sh" ]; then
    # shellcheck source=/dev/null
    source "$HERE/env.local.sh"
fi
