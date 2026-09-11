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
        )
        if key[0] and key in cache:
            self.prompt_cache = _copy_prompt(cache.pop(key))
            self._voice_cache_hits = getattr(self, '_voice_cache_hits', 0) + 1
        elif key[0]:
            self.prompt_cache['ref_audio_path'] = None
            self.prompt_cache['prompt_text'] = None
        self._in_live_run = True
        try:
            yield from corrected_run(self, inputs)
        finally:
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
