"""CLI: promote an "Other topics" entry to a full digest.  python promote.py 2026-09-29 2609.33364"""

import argparse

from core.promote import promote


def main() -> int:
    ap = argparse.ArgumentParser(
        description='Generate a full LLM digest for one paper of a past report.'
    )
    ap.add_argument('date', help='listing date YYYY-MM-DD')
    ap.add_argument('pid', help='arXiv id, e.g. 2609.33364 (version suffix optional)')
    ap.add_argument('--no-rebuild', action='store_true', help='skip site and wiki rebuild')
    a = ap.parse_args()
    pid = a.pid.split('v')[0] if a.pid.count('.') == 1 else a.pid
    info = promote(a.date, pid, rebuild=not a.no_rebuild)
    print(
        f'⬆️  {info["pid"]} ({info["date"]} [{info["number"]}]) -> {", ".join(info["topics"])} via {info["provider"]}'
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
