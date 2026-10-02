"""TF-IDF features over the corpus (port of arxiv-sanity-lite ``compute.py``).

Every paper is represented by the l2-normalised TF-IDF vector of
``title + abstract + authors`` with unigrams and bigrams, exactly as in
arxiv-sanity-lite. The matrix is cached in ``data/features.pkl`` together
with a corpus fingerprint and rebuilt automatically when papers are added.
"""

import os
import pickle

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from core import corpus

FEATURES_PATH = os.path.join(corpus.DATA_DIR, 'features.pkl')
MAX_FEATURES = int(os.getenv('SANITY_MAX_FEATURES', '20000'))


def _vectorizer(n_docs: int) -> TfidfVectorizer:
    # arxiv-sanity-lite defaults are min_df=5 / max_df=0.1 for a ~30k corpus;
    # a daily-report corpus starts with a few dozen papers, so scale the
    # document-frequency cut-offs down until the corpus has grown.
    min_df = 1 if n_docs < 100 else 2 if n_docs < 1000 else 5
    max_df = 1.0 if n_docs < 200 else 0.1
    return TfidfVectorizer(
        input='content',
        encoding='utf-8',
        decode_error='replace',
        strip_accents='unicode',
        lowercase=True,
        analyzer='word',
        stop_words='english',
        token_pattern=r'(?u)\b[a-zA-Z_][a-zA-Z0-9_]+\b',
        ngram_range=(1, 2),
        max_features=MAX_FEATURES,
        norm='l2',
        use_idf=True,
        smooth_idf=True,
        sublinear_tf=True,
        max_df=max_df,
        min_df=min_df,
    )


def _fingerprint() -> tuple[int, float]:
    s = corpus.stats()
    return int(s['n']), float(s['latest'])


def compute_features() -> dict:
    """(Re)build the TF-IDF matrix for the whole corpus and cache it to disk."""
    papers = corpus.all_papers()
    pids = [p['pid'] for p in papers]
    docs = [' '.join([p['title'], p['summary'], p['authors']]) for p in papers]
    if not docs:
        feats = {
            'pids': [],
            'x': None,
            'vocab': {},
            'idf': np.zeros(0),
            'fingerprint': _fingerprint(),
        }
    else:
        v = _vectorizer(len(docs))
        x = v.fit_transform(docs).astype(np.float32)
        feats = {
            'pids': pids,
            'x': x,
            'vocab': v.vocabulary_,
            'idf': v.idf_,
            'fingerprint': _fingerprint(),
        }
    os.makedirs(corpus.DATA_DIR, exist_ok=True)
    with open(FEATURES_PATH, 'wb') as f:
        pickle.dump(feats, f)
    return feats


def load_features() -> dict:
    """Load cached features, recomputing when the corpus changed underneath."""
    try:
        with open(FEATURES_PATH, 'rb') as f:
            feats = pickle.load(f)
        if feats.get('fingerprint') == _fingerprint():
            return feats
    except (OSError, pickle.UnpicklingError, EOFError, AttributeError):
        pass
    return compute_features()
