"""Persistent semantic vectors + BM25, reciprocal-rank fusion, neural reranking."""
import hashlib
import json
import re
import threading
import time
from collections import OrderedDict
from copy import deepcopy
from datetime import date
import numpy as np
from .config import settings
from .db import conn
from .rag_chunking import split_text, family, powers
from . import rag_models

INDEX_VERSION = 'structure-v4-f32:' + rag_models.model_id()
_LOCK = threading.RLock()
_CACHE = None
_RESULTS = OrderedDict()


def tokens(text):
    text = re.sub(r'\s+', '', text.lower())
    out = re.findall(r'[a-z0-9][a-z0-9_.+-]*', text)
    for run in re.findall(r'[\u4e00-\u9fff]+', text):
        out.extend(run[i:i + 2] for i in range(max(1, len(run) - 1)))
    return out


def encode_vector(text):
    return rag_models.embed([text])[0].astype('<f4').tobytes()


def encode_vectors(texts):
    return [v.astype('<f4').tobytes() for v in rag_models.embed(texts)]


def _snapshot():
    """Read DB revision and rows in one transaction; failed writes never publish."""
    global _CACHE
    import faiss
    from rank_bm25 import BM25Okapi
    faiss.omp_set_num_threads(1)
    path = str(settings.database_path.resolve())
    with conn() as c:
        c.execute('BEGIN')
        revision = c.execute('SELECT revision FROM rag_state WHERE id=1').fetchone()[0]
        model = rag_models.model_id()
        key = (path, revision, model)
        if _CACHE and _CACHE['key'] == key:
            return _CACHE
        raw_rows = [dict(row) for row in c.execute('''SELECT ch.*,d.name,d.brand,d.series,d.year,
                d.version,d.source_url,d.license,d.valid_until FROM chunks ch JOIN documents d ON d.id=ch.document_id''')]
    rows = []
    for row in raw_rows:
        row['meta'] = json.loads(row['metadata'] or '{}')
        if row['embedding_model'] == INDEX_VERSION and row['embedding'] and len(row['embedding']) == rag_models.dimension() * 4:
            rows.append(row)
    folder = settings.database_path.with_suffix('.rag-index')
    folder.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    for row in rows:
        digest.update(str(row['id']).encode())
        digest.update(row['embedding'])
    fingerprint = {'revision': revision, 'model': model, 'digest': digest.hexdigest(), 'count': len(rows),
                   'chunk_version': INDEX_VERSION}
    manifest_path, index_path = folder / 'manifest.json', folder / 'vectors.faiss'
    index = None
    try:
        if json.loads(manifest_path.read_text(encoding='utf-8')) == fingerprint:
            index = faiss.deserialize_index(np.frombuffer(index_path.read_bytes(), dtype=np.uint8).copy())
            if index.ntotal != len(rows) or index.d != rag_models.dimension():
                index = None
    except (OSError, ValueError, RuntimeError):
        pass
    if index is None:
        index = faiss.IndexIDMap2(faiss.IndexFlatIP(rag_models.dimension()))
        if rows:
            vectors = np.vstack([np.frombuffer(row['embedding'], dtype='<f4') for row in rows])
            index.add_with_ids(vectors, np.array([r['id'] for r in rows], dtype=np.int64))
        # Publishing the manifest last makes interrupted writes rebuildable.
        pending = index_path.with_suffix('.tmp')
        pending.write_bytes(faiss.serialize_index(index).tobytes())
        pending.replace(index_path)
        pending = manifest_path.with_suffix('.tmp')
        pending.write_text(json.dumps(fingerprint), encoding='utf-8')
        pending.replace(manifest_path)
    corpus = [tokens(row['search_text'] or row['content']) or ['_empty_'] for row in rows]
    _CACHE = {'key': key, 'rows': rows, 'index': index, 'bm25': BM25Okapi(corpus) if corpus else None,
              'revision': revision, 'unindexed': len(raw_rows) - len(rows), 'path': str(index_path)}
    _RESULTS.clear()
    return _CACHE


def _eligible(row, brand, series, year, scope, include_blocked=False):
    if brand and row['brand'] != brand:
        return False
    if year and row['year'] and row['year'] != year:
        return False
    if row['valid_until'] and row['valid_until'] < date.today().isoformat():
        return False
    meta = row['meta']
    if meta.get('blocked') and not include_blocked:
        return False
    if series and row['series'] != series:
        if family(row['series']) != family(series) or meta.get('kind') not in ['faq', 'note']:
            return False
    declared = set(meta.get('powers', ['all']))
    return not scope or 'all' in declared or bool(declared.intersection(scope))


def retrieve_with_trace(question, brand='', series='', year='', k=5):
    from .local_answers import normalize_question
    started = time.perf_counter()
    with _LOCK:
        state = _snapshot()
        cache_key = (state['key'], date.today().isoformat(), question, brand, series, year, k)
        if cache_key in _RESULTS:
            sources, trace = deepcopy(_RESULTS[cache_key])
            trace.update(cache_hit=True, latency_ms=round((time.perf_counter() - started) * 1000, 1))
            return sources, trace
        scope = powers(question) or powers(series)
        rows = [r for r in state['rows'] if _eligible(r, brand, series, year, scope)]
        trace = {'pipeline': 'structure -> BGE -> FAISS + BM25 -> RRF -> BGE cross-encoder -> parent context',
                 'index_revision': state['revision'], 'eligible_chunks': len(rows), 'cache_hit': False,
                 'query_power': scope, 'dense_candidates': [], 'bm25_candidates': [], 'reranked': [], 'warnings': []}
        blocked = [r for r in state['rows'] if _eligible(r, brand, series, year, scope, True) and r['meta'].get('blocked')]
        is_price = bool(re.search(r'价格|多少钱|多少米|售价|指导价|报价|落地', question))
        blocked_warnings = sorted({w for r in blocked for w in r['meta'].get('warnings', [])}) if is_price else []
        trace['warnings'] = blocked_warnings
        if not rows:
            return [], trace
        by_id = {r['id']: r for r in rows}
        expanded = normalize_question(question)
        if re.search(r'多少米|多少钱|几个[Ww万]|什么价|售价|落地', question):
            expanded += ' 价格 指导价 报价'
        qv = rag_models.embed([expanded], query=True)
        distances, labels = state['index'].search(qv, state['index'].ntotal)
        dense = [(int(i), float(s)) for i, s in zip(labels[0], distances[0]) if int(i) in by_id][:24]
        bm_scores = state['bm25'].get_scores(tokens(expanded))
        sparse = sorted([(r['id'], float(s)) for r, s in zip(state['rows'], bm_scores)
                         if r['id'] in by_id and s > 0], key=lambda x: x[1], reverse=True)[:24]
        fused = {}
        for results in [dense, sparse]:
            for rank, (chunk_id, _) in enumerate(results, 1):
                fused[chunk_id] = fused.get(chunk_id, 0) + 1 / (60 + rank)
        unique, seen = [], set()
        for chunk_id in sorted(fused, key=fused.get, reverse=True):
            row = by_id[chunk_id]
            parent = (row['document_id'], row['meta'].get('parent_key', row['id']))
            if parent not in seen:
                unique.append(chunk_id)
                seen.add(parent)
            if len(unique) >= max(4, min(24, settings.rag_rerank_candidates)):
                break
        t = time.perf_counter()
        scores = rag_models.rerank(expanded, [by_id[i]['search_text'] for i in unique])
        def intent_score(item):
            chunk_id, score = item
            meta = by_id[chunk_id]['meta']
            # Prefer an applicable version-specific policy over generic sales text.
            specific = bool(len(scope) == 1 and meta.get('powers') == scope)
            return score + (.22 if specific and score > .10 and re.search(r'价格|多少钱|多少米|免息|分期|贷款', question) else 0)
        reranked = sorted(zip(unique, scores), key=intent_score, reverse=True)
        trace['rerank_ms'] = round((time.perf_counter() - t) * 1000, 1)
        trace['dense_candidates'] = [{'chunk_id': i, 'score': round(s, 5)} for i, s in dense]
        trace['bm25_candidates'] = [{'chunk_id': i, 'score': round(s, 5)} for i, s in sparse]
        trace['reranked'] = [{'chunk_id': i, 'score': round(s, 5), 'rrf_score': round(fused[i], 6),
                              'title': by_id[i]['meta'].get('title', '')} for i, s in reranked]
        sources = []
        dense_map, sparse_map = dict(dense), dict(sparse)
        threshold = max(.015, max(scores, default=0) * .06)
        for chunk_id, score in reranked[:max(1, min(k, 12))]:
            row, meta = by_id[chunk_id], by_id[chunk_id]['meta']
            if score < threshold:
                continue
            sources.append({'document_id': row['document_id'], 'document_name': row['name'],
                            'chunk_id': chunk_id, 'version': row['version'], 'page': row['page'],
                            'source_url': row['source_url'], 'license': row['license'],
                            'content': row['parent_content'] or row['content'],
                            'matched_text': row['search_text'], 'score': round(score, 5),
                            'score_kind': 'neural_reranker_relevance_not_probability',
                            'retrieval_scores': {'dense': dense_map.get(chunk_id), 'bm25': sparse_map.get(chunk_id),
                                                 'rrf': fused[chunk_id], 'reranker': score},
                            'metadata': {'brand': row['brand'], 'series': row['series'], 'year': row['year'], **meta}})
        trace['warnings'] = sorted(set(blocked_warnings) | {w for s in sources for w in s['metadata'].get('warnings', [])})
        trace['latency_ms'] = round((time.perf_counter() - started) * 1000, 1)
        _RESULTS[cache_key] = deepcopy((sources, trace))
        while len(_RESULTS) > 128:
            _RESULTS.popitem(last=False)
        return sources, trace


def retrieve(question, brand='', series='', year='', k=5):
    return retrieve_with_trace(question, brand, series, year, k)[0]


def index_status():
    with _LOCK:
        state = _snapshot()
        return {**rag_models.model_status(), 'ready': bool(state['rows']) and not state['unindexed'], 'mode': 'semantic-hybrid',
                'provider': 'FAISS + BM25 + BGE reranker', 'index_version': INDEX_VERSION,
                'index_revision': state['revision'], 'chunks': len(state['rows']), 'unindexed_chunks': state['unindexed'],
                'index_file': state['path'], 'rerank_candidates': settings.rag_rerank_candidates,
                'blocked_chunks': sum(bool(r['meta'].get('blocked')) for r in state['rows'])}


def data_quality():
    with _LOCK:
        state = _snapshot()
        issues, seen = [], set()
        for row in state['rows']:
            meta = row['meta']
            key = (row['document_id'], meta.get('parent_key', row['id']))
            if key in seen or not meta.get('warnings'):
                continue
            seen.add(key)
            issues.append({'document_id': row['document_id'], 'document_name': row['name'],
                           'chunk_id': row['id'], 'title': meta.get('title'), 'blocked': meta.get('blocked'),
                           'warnings': meta['warnings'], 'original': row['content']})
        return issues
