"""CLI for the Obsidian wiki: build (idempotent sync), lint, fold (weekly rollup), log."""

import argparse
import json

from core import wiki


def main() -> int:
    ap = argparse.ArgumentParser(
        description='Maintain the Obsidian wiki built from the daily reports.'
    )
    sub = ap.add_subparsers(dest='cmd', required=True)
    b = sub.add_parser(
        'build', help='sync notes with the corpus and digests (preserves human edits)'
    )
    b.add_argument('--dry-run', action='store_true', help='report what would change; write nothing')
    lt = sub.add_parser(
        'lint', help='dead links, orphans, metadata gaps, stale indexes, overdue reviews'
    )
    lt.add_argument(
        '--strict', action='store_true', help='exit 1 on dead links / gaps / stale indexes'
    )
    lt.add_argument('--no-stale', action='store_true', help='skip the (slower) stale-index probe')
    lt.add_argument('--json', action='store_true')
    f = sub.add_parser('fold', help='write the weekly rollup note')
    f.add_argument('--week', help='ISO week, e.g. 2026-W40 (default: current week)')
    sub.add_parser(
        'html', help='export the vault to <REPORTS_DIR>/wiki/*.html (linked with the reports)'
    )
    lg = sub.add_parser('log', help='show the operations journal')
    lg.add_argument('-n', type=int, default=20)
    a = ap.parse_args()

    if a.cmd == 'build':
        s = wiki.Build(dry_run=a.dry_run).run()
        verb = 'would change' if a.dry_run else 'wrote'
        print(
            f'📚 wiki {verb}: +{s["created"]} created, ~{s["updated"]} updated, ={s["unchanged"]} unchanged '
            f'({s["papers"]} papers, {s["days"]} days) -> {wiki.WIKI_DIR}  op {s["op"]}'
        )
        for p in s['created_paths'][:10]:
            print(f'   + {p}')
        for p in s['updated_paths'][:10]:
            print(f'   ~ {p}')
        return 0
    if a.cmd == 'lint':
        r = wiki.lint(stale_check=not a.no_stale)
        if a.json:
            print(json.dumps(r, ensure_ascii=False, indent=1))
        else:
            print(wiki.format_lint(r))
        bad = r['dead_links'] or r['metadata_gaps'] or r['stale_indexes']
        return 1 if (a.strict and bad) else 0
    if a.cmd == 'fold':
        print(f'🧾 wrote {wiki.fold(a.week)}')
        return 0
    if a.cmd == 'html':
        n = wiki.export_html()
        print(f'🌐 exported {n} notes -> {wiki.HTML_DIR}')
        return 0
    if a.cmd == 'log':
        for e in wiki.read_log()[-a.n :]:
            print(json.dumps(e, ensure_ascii=False))
        return 0
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
