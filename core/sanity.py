"""Search, similarity and SVM recommendations (port of arxiv-sanity-lite ``serve.py``).

* :func:`search_rank` -- keyword ranking with the same weights as
  arxiv-sanity-lite (20 per title word, 10 per author word, up to 3 per
  abstract occurrence).
* :func:`similar_rank` -- cosine similarity of TF-IDF vectors ("inspect").
* :func:`svm_rank` -- a ``LinearSVC(class_weight='balanced', C=0.01)`` trained
  with the user's starred papers as positives and every other paper as
  negatives; the decision function ranks the corpus. The classifier weights
  also expose which vocabulary terms drive the recommendation.
* :func:`time_filter` -- keep only papers from the last *N* listing days.
"""

import datetime

import numpy as np
from sklearn import svm

from core import corpus
from core.features import load_features

DEFAULT_C = 0.01


def _match_scores(q: str, papers: list[dict]) -> list[tuple[float, str]]:
    qs = q.lower().strip().split()
    if not qs:
        return []

    def match(s: str) -> int:
        s = s.lower()
        return sum(min(3, s.count(qp)) for qp in qs)

    def matchu(s: str) -> int:
        s = s.lower()
        return sum(int(s.count(qp) > 0) for qp in qs)

    pairs = []
    for p in papers:
        score = 10.0 * matchu(p['authors']) + 20.0 * matchu(p['title']) + 1.0 * match(p['summary'])
        if score > 0:
            pairs.append((score, p['pid']))
    pairs.sort(reverse=True)
    return pairs


def search_rank(q: str) -> tuple[list[str], list[float]]:
    """Keyword search over title / authors / abstract across the whole corpus."""
    pairs = _match_scores(q, corpus.all_papers())
    return [p for _, p in pairs], [s for s, _ in pairs]


def similar_rank(pid: str, limit: int | None = None) -> tuple[list[str], list[float]]:
    """Papers most similar to ``pid`` by TF-IDF cosine similarity (``pid`` excluded)."""
    feats = load_features()
    pids, x = feats['pids'], feats['x']
    if x is None or pid not in pids:
        return [], []
    i = pids.index(pid)
    sims = (x @ x[i].T).toarray().ravel()
    order = [j for j in np.argsort(-sims) if j != i]
    if limit:
        order = order[:limit]
    return [pids[j] for j in order], [float(sims[j]) for j in order]


def svm_rank(
    positive_pids: list[str], C: float = DEFAULT_C
) -> tuple[list[str], list[float], list[dict]]:
    """Rank the corpus by an SVM trained on ``positive_pids`` vs. everything else.

    Returns ``(pids, scores, words)`` where ``scores`` are 100x the decision
    function and ``words`` lists the 40 most positive and 20 most negative
    vocabulary weights, as in arxiv-sanity-lite.
    """
    feats = load_features()
    pids, x = feats['pids'], feats['x']
    if x is None:
        return [], [], []
    ptoi = {p: i for i, p in enumerate(pids)}
    y = np.zeros(len(pids), dtype=np.float32)
    for p in positive_pids:
        if p in ptoi:
            y[ptoi[p]] = 1.0
    if y.sum() == 0 or y.sum() == len(y):
        return [], [], []

    clf = svm.LinearSVC(class_weight='balanced', max_iter=10000, tol=1e-6, C=C)
    clf.fit(x, y)
    s = clf.decision_function(x)
    order = np.argsort(-s)

    ivocab = {v: k for k, v in feats['vocab'].items()}
    w = clf.coef_[0]
    worder = np.argsort(-w)
    words = [
        {'word': ivocab[int(ix)], 'weight': float(w[ix])}
        for ix in list(worder[:40]) + list(worder[-20:])
    ]
    return [pids[i] for i in order], [100.0 * float(s[i]) for i in order], words


def time_filter(pids: list[str], scores: list[float], days: int) -> tuple[list[str], list[float]]:
    """Keep papers whose listing date is within the last ``days`` days."""
    if not days or days <= 0:
        return pids, scores
    cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    meta = corpus.get_papers(pids)
    keep = [i for i, p in enumerate(pids) if p in meta and meta[p]['report_date'] > cutoff]
    return [pids[i] for i in keep], [scores[i] for i in keep]


def attach(pids: list[str], scores: list[float]) -> list[dict]:
    """Join ranked ids back to paper records, adding a ``score`` field."""
    meta = corpus.get_papers(pids)
    out = []
    for pid, score in zip(pids, scores, strict=True):
        p = meta.get(pid)
        if p:
            p = dict(p)
            p['score'] = score
            out.append(p)
    return out
