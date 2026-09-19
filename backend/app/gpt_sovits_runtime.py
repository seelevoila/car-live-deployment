"""Scoped compatibility fixes for the bundled GPT-SoVITS API runtime.

Installed only by scripts/gpt_sovits_api.py in the model's Python environment.
The external checkout is never rewritten. Source guards fail closed if its
implementation changes, instead of silently patching an incompatible version.
"""
from __future__ import annotations

import ast
from collections import OrderedDict
import inspect
from pathlib import Path
import textwrap
import time


def corrected_source(source: str, kind: str) -> ast.Module:
    tree = ast.parse(textwrap.dedent(source))
    matches = 0
    for node in ast.walk(tree):
        if kind == 'semantic' and isinstance(node, ast.If) and ast.unparse(node.test) == 'score[argmax_idx] >= 0 and argmax_idx + 1 >= chunk_length':
            for child in node.body:
                if isinstance(child, ast.Expr) and isinstance(child.value, ast.Yield):
                    if ast.unparse(child.value.value) != '(y[:, curr_ptr:], False)':
                        raise RuntimeError('Unsupported GPT-SoVITS semantic yield')
                    # Only advance and emit through the chosen boundary. The
                    # lookahead tokens remain pending for the next chunk.
                    child.value.value = ast.parse('(y[:, curr_ptr:curr_ptr + argmax_idx + 1], False)', mode='eval').body
                    matches += 1
            node.orelse = ast.parse('''
if token_counter >= chunk_length * 2:
    yield y[:, curr_ptr:], False
    curr_ptr = y.shape[1]
    token_counter = 0
''').body
        elif kind == 'audio' and isinstance(node, ast.If) and ast.unparse(node.test) == 'not is_first_chunk and (not is_final)':
            # The original body already handles final/non-final slices, but
            # its condition excluded the final branch, replaying the overlap.
            node.test = ast.parse('not is_first_chunk', mode='eval').body
            matches += 1
    if matches != 1:
        raise RuntimeError(f'Unsupported GPT-SoVITS {kind} source: expected one boundary, found {matches}')
    if kind == 'audio':
        function = tree.body[0]
        for index, node in enumerate(function.body):
            if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 't1' for target in node.targets):
                function.body[index:index] = ast.parse("if inputs.get('_prepare_reference_only', False):\n    return").body
                break
        else:
            if any(isinstance(node, ast.Name) and node.id == 'inputs' for node in ast.walk(function)):
                raise RuntimeError('Unsupported GPT-SoVITS reference preparation')
    return ast.fix_missing_locations(tree)


def _patch(function, kind):
    original = inspect.unwrap(function)
    tree = corrected_source(inspect.getsource(original), kind)
    namespace = dict(original.__globals__)
    exec(compile(tree, f'<car-live-{kind}-boundary>', 'exec'), namespace)
    return namespace[original.__name__]


def _stamp(path):
    if not path:
        return None
    file = Path(path).resolve()
    stat = file.stat()
    return (str(file), stat.st_size, stat.st_mtime_ns)


def _copy_prompt(cache):
    # Tensors are immutable conditioning here; copy mutable containers only.
    return {key: list(value) if isinstance(value, list) else value for key, value in cache.items()}


def _speaker_anchor_key(path, auxiliary_paths=None, threshold=.85):
    return (_stamp(path), None if auxiliary_paths is None else tuple(_stamp(p) for p in auxiliary_paths), float(threshold))


def _original_speaker_embedding(pipeline, path, auxiliary_paths=None, threshold=.85):
    """Keep semantic/acoustic references intact while using an accepted voice anchor."""
    if not getattr(pipeline, 'is_v2pro', False) or pipeline.sv_model is None:
        raise ValueError('A separate speaker reference requires a v2Pro speaker encoder')
    stamp = _speaker_anchor_key(path, auxiliary_paths, threshold)
    cache = getattr(pipeline, '_speaker_anchor_cache', OrderedDict())
    pipeline._speaker_anchor_cache = cache
    if stamp not in cache:
        import torch
        previous = _copy_prompt(pipeline.prompt_cache)
        try:
            with torch.no_grad():
                _, waveform = pipeline._get_ref_spec(path)
                native = pipeline.sv_model.compute_embedding3(waveform).detach().clone()
                if auxiliary_paths is None:
                    cache[stamp] = native
                else:
                    # Use the scorer itself, including its speech-region crop,
                    # CPU float32 model, screening, weights and normalization.
                    # Decoder conditioning was trained on unnormalized vectors;
                    # retain the native primary norm while sharing the exact
                    # cosine target direction. A unit vector alone changes gain.
                    from .voice_similarity import _load_model, _reference_target, reference_weights
                    scoring = getattr(pipeline, '_speaker_target_scorer', None)
                    if scoring is None:
                        root = Path(inspect.getfile(type(pipeline.sv_model))).resolve().parents[1]
                        scoring = _load_model(root, root/'GPT_SoVITS/pretrained_models/sv/pretrained_eres2netv2w24s4ep4.ckpt')
                        pipeline._speaker_target_scorer = scoring
                    paths = [Path(path), *map(Path, auxiliary_paths)]
                    target, accepted, scores = _reference_target(paths, *scoring, threshold)
                    scaled = target.to(device=native.device).reshape_as(native) * native.float().norm()
                    cache[stamp] = scaled.to(dtype=native.dtype).detach().clone()
                    pipeline._speaker_anchor_details = {'paths':list(map(str, paths)),
                        'accepted_paths':list(map(str, accepted)), 'reference_scores':scores,
                        'weights':reference_weights(scores, threshold), 'threshold':threshold,
                        'native_primary_norm':float(native.float().norm()),
                        'condition_norm':float(cache[stamp].float().norm()),
                        'target_condition_cosine':float(torch.nn.functional.cosine_similarity(
                            target.reshape(1,-1), cache[stamp].float().cpu().reshape(1,-1)).item())}
        finally:
            # _get_ref_spec also writes raw_audio/raw_sr. It must not replace
            # the semantic prompt or acoustic conditioning for this request.
            pipeline.prompt_cache = previous
        while len(cache) > 8:
            cache.popitem(last=False)
    return cache[stamp]


def install():
    from AR.models.t2s_model import Text2SemanticDecoder
    from GPT_SoVITS.TTS_infer_pack.TTS import TTS

    Text2SemanticDecoder.infer_panel_naive = _patch(Text2SemanticDecoder.infer_panel_naive, 'semantic')
    corrected_run = _patch(TTS.run, 'audio')
    install_reference_cache(TTS, corrected_run)


def install_reference_cache(TTS, corrected_run):
    original_empty_cache = TTS.empty_cache

    for method_name in ('init_t2s_weights', 'init_vits_weights'):
        original = getattr(TTS, method_name)

        def invalidate(self, *args, _original=original, **kwargs):
            self._voice_cache = OrderedDict()
            self._speaker_anchor_cache = OrderedDict()
            self._voice_cache_epoch = getattr(self, '_voice_cache_epoch', 0) + 1
            if hasattr(self, 'prompt_cache'):
                self.prompt_cache['ref_audio_path'] = None
                self.prompt_cache['prompt_text'] = None
            return _original(self, *args, **kwargs)

        setattr(TTS, method_name, invalidate)

    def run(self, inputs):
        cache = getattr(self, '_voice_cache', OrderedDict())
        self._voice_cache = cache
        epoch = getattr(self, '_voice_cache_epoch', 0)
        key = (
            _stamp(inputs.get('ref_audio_path')),
            tuple(_stamp(path) for path in (inputs.get('aux_ref_audio_paths') or []) if path),
            inputs.get('prompt_text') or '', inputs.get('prompt_lang'),
            _speaker_anchor_key(inputs.get('speaker_ref_audio_path'), inputs.get('speaker_aux_ref_audio_paths'),
                                inputs.get('speaker_similarity_threshold', .85)),
        )
        if key[0] and key in cache:
            self.prompt_cache = _copy_prompt(cache.pop(key))
            self._voice_cache_hits = getattr(self, '_voice_cache_hits', 0) + 1
        elif key[0]:
            self.prompt_cache['ref_audio_path'] = None
            self.prompt_cache['prompt_text'] = None
        speaker_reference = inputs.get('speaker_ref_audio_path')
        original_compute = None
        if speaker_reference:
            anchor = _original_speaker_embedding(self, speaker_reference, inputs.get('speaker_aux_ref_audio_paths'),
                                                 inputs.get('speaker_similarity_threshold', .85))
            original_compute = self.sv_model.compute_embedding3
            self.sv_model.compute_embedding3 = lambda waveform: anchor.clone()
        self._in_live_run = True
        try:
            yield from corrected_run(self, inputs)
        finally:
            if original_compute is not None:
                self.sv_model.compute_embedding3 = original_compute
            self._in_live_run = False
            if (key[0] and epoch == getattr(self, '_voice_cache_epoch', 0)
                    and self.prompt_cache.get('ref_audio_path') == inputs.get('ref_audio_path')):
                cache[key] = _copy_prompt(self.prompt_cache)
                while len(cache) > 8:
                    cache.popitem(last=False)

    def empty_cache(self):
        # Retain the CUDA allocator between short requests. Model switches and
        # failures still call the original cleanup; periodic GC bounds Python
        # cycles during a long-running broadcast.
        now = time.monotonic()
        if getattr(self, '_in_live_run', False) and now - getattr(self, '_last_cache_cleanup', 0) < 60:
            return
        self._last_cache_cleanup = now
        original_empty_cache(self)

    TTS.run = run
    TTS.empty_cache = empty_cache
