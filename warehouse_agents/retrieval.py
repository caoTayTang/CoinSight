"""Bounded local runbook retrieval. BM25 always works; neural retrieval is opt-in.

No arbitrary file paths, remote document ingestion, pickle index, or executable content.
"""

from collections import Counter
from functools import lru_cache
from pathlib import Path
import hashlib
import math
import os
import re
import unicodedata
import numpy as np
from warehouse_agents.telemetry import traced

ROOT = Path(__file__).parent / 'knowledge'
ALLOWED = ('service_unreachable', 'feature_drift', 'missing_candles', 'reconciliation', 'security')


def tokens(text):
    text = unicodedata.normalize('NFKD', text.lower()).replace('đ', 'd')
    return re.findall(r'[a-z0-9_]+', ''.join(c for c in text if not unicodedata.combining(c)))


@lru_cache(maxsize=1)
def documents():
    chunks = []
    for name in ALLOWED:
        path = ROOT / (name + '.md')
        data = path.read_bytes()
        text = data.decode('utf-8')
        if len(data) > 32000:
            raise ValueError('Runbook too large')
        digest = hashlib.sha256(data).hexdigest()
        title = text.splitlines()[0].lstrip('# ')
        # Paragraph boundaries with a strict cap; stable content IDs and source hashes.
        for i, paragraph in enumerate(text.split('\n\n')[1:]):
            if paragraph.strip():
                for offset in range(0, len(paragraph), 1600):
                    content = paragraph[offset : offset + 1600].strip()
                    chunks.append(
                        dict(
                            id=f'{name}:{i}:{offset}',
                            title=title,
                            source=f'warehouse_agents/knowledge/{name}.md',
                            sha256=digest,
                            text=content,
                            citation=f'[runbook:{name}:{i}:{offset}]',
                        )
                    )
    return tuple(chunks)


def bm25(query, docs):
    counts = [Counter(tokens(d['title'] + ' ' + d['text'])) for d in docs]
    lengths = np.array([sum(c.values()) for c in counts], dtype=float)
    avg = max(float(lengths.mean()), 1)
    scores = np.zeros(len(docs))
    for word in set(tokens(query)):
        df = sum(word in c for c in counts)
        idf = math.log(1 + (len(docs) - df + 0.5) / (df + 0.5))
        freq = np.array([c[word] for c in counts], dtype=float)
        scores += idf * freq * 2.5 / (freq + 1.5 * (0.25 + 0.75 * lengths / avg))
    return scores


@lru_cache(maxsize=1)
def neural_index():
    # Models must be downloaded explicitly by the operator. No network at request time.
    from sentence_transformers import SentenceTransformer, CrossEncoder

    embed = SentenceTransformer(
        os.environ['SRE_EMBEDDING_PATH'], local_files_only=True, trust_remote_code=False, device='cpu'
    )
    reranker = CrossEncoder(
        os.environ['SRE_RERANKER_PATH'], local_files_only=True, trust_remote_code=False, device='cpu'
    )
    matrix = embed.encode([d['title'] + '\n' + d['text'] for d in documents()], normalize_embeddings=True)
    return embed, reranker, matrix


@traced('retrieval.runbooks')
def search(query, top_k=3, mode=None):
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 2000:
        raise ValueError('Query must contain 1..2000 characters')
    if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 5:
        raise ValueError('top_k must be 1..5')
    mode = mode or os.getenv('SRE_RETRIEVAL_MODE', 'bm25')
    if mode not in ('bm25', 'dense', 'hybrid', 'hybrid_rerank'):
        raise ValueError('Unsupported retrieval mode')
    docs = documents()
    sparse = bm25(query, docs)
    order = sorted(range(len(docs)), key=lambda i: (-sparse[i], docs[i]['id']))
    scores = sparse
    if mode != 'bm25':
        embed, reranker, matrix = neural_index()
        dense = matrix @ embed.encode([query], normalize_embeddings=True)[0]
        dense_order = np.argsort(-dense).tolist()
        if mode == 'dense':
            scores, order = dense, dense_order
        else:
            # Reciprocal rank fusion; no raw BM25/cosine score scale assumptions.
            scores = np.zeros(len(docs))
            for ranking in (order, dense_order):
                for rank, i in enumerate(ranking):
                    scores[i] += 1 / (60 + rank + 1)
            order = np.argsort(-scores).tolist()
            if mode == 'hybrid_rerank':
                candidates = order[: min(12, len(docs))]
                values = reranker.predict(
                    [(query, docs[i]['title'] + '\n' + docs[i]['text']) for i in candidates]
                )
                scores = np.full(len(docs), -np.inf)
                for i, value in zip(candidates, values):
                    scores[i] = float(value)
                order = sorted(candidates, key=lambda i: -scores[i])
    # Sparse no-overlap can deterministically abstain; neural ranking is NOT an answerability test.
    selected = [i for i in order[:top_k] if mode != 'bm25' or scores[i] > 0]
    hits = [dict(docs[i], score=float(scores[i])) for i in selected]
    return dict(
        status='available' if hits else 'unavailable',
        evidence_kind='procedural_documentation',
        mode=mode,
        hits=hits,
        corpus_sha256=hashlib.sha256(''.join(d['sha256'] + d['id'] for d in docs).encode()).hexdigest(),
        scope='Procedural runbooks, not live observations. Scores do not establish answerability.',
        reason=None if hits else 'No lexical overlap with allowlisted runbooks.',
    )


def validate_citations(answer, evidence):
    allowed = {
        hit['citation']
        for item in evidence
        if item.get('tool') == 'search_runbooks'
        for hit in item.get('result', {}).get('hits', [])
    }
    cited = set(re.findall(r'\[runbook:[^\]\n]+\]', answer))
    unknown = sorted(cited - allowed)
    if unknown:
        # Strip only the unverifiable citations. Discarding the whole answer threw away correct
        # observations in 4 of 29 dev eval cases (see docs/evaluation.md).
        for citation in unknown:
            answer = answer.replace(citation, '[unverified citation removed]')
        answer += (
            f'\n\n> {len(unknown)} runbook citation(s) could not be verified against retrieved runbooks '
            'and were removed. Use search_runbooks before following a procedure.'
        )
    return answer, unknown
