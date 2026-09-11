"""Local, bounded CPU inference. No torch, CUDA, remote code, or runtime downloads."""
import json
import threading
from functools import lru_cache
import numpy as np
from .config import settings

INFERENCE_LOCK = threading.RLock()


class ModelUnavailable(RuntimeError):
    pass


@lru_cache(maxsize=2)
def _load(role, root):
    import onnxruntime as ort
    from tokenizers import Tokenizer
    folder = root / role
    if not (folder / 'model_quantized.onnx').is_file() or not (folder / 'tokenizer.json').is_file():
        raise ModelUnavailable('检索模型尚未安装，请运行 scripts/setup_rag_models.py')
    options = ort.SessionOptions()
    options.intra_op_num_threads = max(1, min(4, settings.rag_threads))
    options.inter_op_num_threads = 1
    options.enable_cpu_mem_arena = False
    session = ort.InferenceSession(str(folder / 'model_quantized.onnx'), sess_options=options,
                                 providers=['CPUExecutionProvider'])
    tokenizer = Tokenizer.from_file(str(folder / 'tokenizer.json'))
    config = json.loads((folder / 'config.json').read_text(encoding='utf-8'))
    tokenizer.enable_padding(pad_id=config.get('pad_token_id', 0), pad_token='<pad>' if role == 'reranker' else '[PAD]')
    tokenizer.enable_truncation(max_length=384)
    return session, tokenizer


def _run(role, inputs):
    session, tokenizer = _load(role, settings.rag_model_dir)
    encoded = tokenizer.encode_batch(inputs)
    arrays = {'input_ids': np.array([x.ids for x in encoded], dtype=np.int64),
              'attention_mask': np.array([x.attention_mask for x in encoded], dtype=np.int64),
              'token_type_ids': np.array([x.type_ids for x in encoded], dtype=np.int64)}
    return session.run(None, {x.name: arrays[x.name] for x in session.get_inputs()})[0]


def embed(texts, query=False):
    if not texts:
        return np.zeros((0, dimension()), dtype=np.float32)
    if query:
        texts = [settings.rag_embedding_query_prefix + x for x in texts]
    batches = []
    with INFERENCE_LOCK:
        for start in range(0, len(texts), 4):
            output = _run('embedding', texts[start:start + 4])
            vector = output[:, 0, :] if output.ndim == 3 else output
            vector = vector.astype(np.float32)
            vector /= np.maximum(np.linalg.norm(vector, axis=1, keepdims=True), 1e-12)
            batches.append(vector)
    return np.concatenate(batches)


def rerank(question, passages):
    scores = []
    with INFERENCE_LOCK:
        # One pair at a time avoids padding all candidates to the longest passage.
        for passage in passages:
            logit = float(_run('reranker', [(question, passage)]).reshape(-1)[0])
            scores.append(float(1 / (1 + np.exp(-np.clip(logit, -40, 40)))))
    return scores


def dimension():
    path = settings.rag_model_dir / 'embedding' / 'config.json'
    return json.loads(path.read_text(encoding='utf-8'))['hidden_size'] if path.exists() else 512


def model_id():
    path = settings.rag_model_dir / 'embedding' / 'manifest.json'
    if not path.exists():
        return 'bge-small-zh-v1.5-onnx-int8-missing'
    manifest = json.loads(path.read_text(encoding='utf-8'))
    digest = manifest['files']['model_quantized.onnx']['sha256'][:12]
    return manifest['repository'] + ':' + digest


def model_status():
    return {'embedding': model_id(), 'dimensions': dimension(),
            'reranker': 'BAAI/bge-reranker-base (Xenova ONNX int8)',
            'device': 'CPUExecutionProvider', 'threads': max(1, min(4, settings.rag_threads)),
            'installed': all((settings.rag_model_dir / role / 'manifest.json').is_file()
                             for role in ['embedding', 'reranker'])}
