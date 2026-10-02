"""CLI for the arxiv-sanity-lite style corpus: import, compute, search, similar, recommend."""

import argparse
import textwrap

from core import corpus
from core.features import compute_features
from core.sanity import attach, search_rank, similar_rank, svm_rank, time_filter


def _print(papers: list[dict], limit: int) -> None:
    for p in papers[:limit]:
        authors = p['authors'] if len(p['authors']) < 70 else p['authors'][:67] + '...'
        print(f'{p["score"]:8.2f}  {p["pid"]:<12} {p["report_date"]} [{p["number"]}]  {p["title"]}')
        print(f'{"":8}  {textwrap.shorten(authors, 100)}')


def main() -> int:
    ap = argparse.ArgumentParser(description='Search, similar papers and recommendations.')
    sub = ap.add_subparsers(dest='cmd', required=True)

    sub.add_parser('stats', help='corpus size and date range')
    sub.add_parser('import-cache', help='backfill the corpus from reports/.cache/*.json')
    sub.add_parser('compute', help='rebuild TF-IDF features')

    s = sub.add_parser('search', help='keyword search')
    s.add_argument('query', nargs='+')
    s.add_argument('--days', type=int, default=0)
    s.add_argument('-n', type=int, default=20)

    s = sub.add_parser('similar', help='papers similar to an arXiv id')
    s.add_argument('pid')
    s.add_argument('-n', type=int, default=20)

    s = sub.add_parser('recommend', help='SVM ranking from starred/positive arXiv ids')
    s.add_argument('--ids', required=True, help='comma-separated arXiv ids (positives)')
    s.add_argument('--days', type=int, default=0)
    s.add_argument('-C', type=float, default=0.01)
    s.add_argument('-n', type=int, default=20)
    s.add_argument('--words', action='store_true', help='show top vocabulary weights')

    a = ap.parse_args()

    if a.cmd == 'stats':
        st = corpus.stats()
        print(
            f'{st["n"]} papers, listings {st["first_date"]} .. {st["last_date"]} ({corpus.DB_PATH})'
        )
    elif a.cmd == 'import-cache':
        n = corpus.import_cache()
        print(f'Imported {n} new papers; corpus now {corpus.stats()["n"]}.')
        compute_features()
    elif a.cmd == 'compute':
        f = compute_features()
        shape = f['x'].shape if f['x'] is not None else (0, 0)
        print(
            f'TF-IDF matrix {shape[0]} papers x {shape[1]} terms -> {corpus.DATA_DIR}/features.pkl'
        )
    elif a.cmd == 'search':
        pids, scores = time_filter(*search_rank(' '.join(a.query)), a.days)
        _print(attach(pids, scores), a.n)
    elif a.cmd == 'similar':
        pid = a.pid.split('v')[0] if a.pid.count('.') == 1 else a.pid
        pids, scores = similar_rank(pid, a.n)
        _print(attach(pids, scores), a.n)
    elif a.cmd == 'recommend':
        pos = [x.strip().split('v')[0] for x in a.ids.split(',') if x.strip()]
        pids, scores, words = svm_rank(pos, C=a.C)
        pids, scores = time_filter(pids, scores, a.days)
        _print([p for p in attach(pids, scores) if p['pid'] not in pos], a.n)
        if a.words:
            print('\n+ ' + ', '.join(w['word'] for w in words[:25]))
            print('- ' + ', '.join(w['word'] for w in words[-10:]))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
