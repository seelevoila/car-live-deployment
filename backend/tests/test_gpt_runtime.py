import ast
from pathlib import Path

import pytest

from app.gpt_sovits_runtime import corrected_source, install_reference_cache
from app.runtime_paths import detect_gpt_sovits_root


SEMANTIC = '''
def generate(y, score, argmax_idx, chunk_length, token_counter, curr_ptr):
    if score[argmax_idx] >= 0 and argmax_idx + 1 >= chunk_length:
        yield y[:, curr_ptr:], False
        token_counter -= argmax_idx + 1
        curr_ptr += argmax_idx + 1
    yield curr_ptr, token_counter
'''


def test_selected_boundary_does_not_replay_lookahead_tokens():
    import numpy as np
    namespace = {}
    exec(compile(corrected_source(SEMANTIC, 'semantic'), '<test>', 'exec'), namespace)
    tokens = np.arange(25).reshape(1, -1)
    chunks = list(namespace['generate'](tokens, [1] * 20, 15, 16, 20, 5))
    assert chunks[0][0].tolist() == [list(range(5, 21))]
    assert chunks[1] == (21, 4)


def test_missing_pause_is_bounded_and_does_not_drop_pending_tokens():
    import numpy as np
    namespace = {}
    exec(compile(corrected_source(SEMANTIC, 'semantic'), '<test>', 'exec'), namespace)
    tokens = np.arange(37).reshape(1, -1)
    chunks = list(namespace['generate'](tokens, [-1] * 32, 0, 16, 32, 5))
    assert chunks[0][0].tolist() == [list(range(5, 37))]
    assert chunks[1] == (37, 0)


def test_final_audio_chunk_also_trims_already_emitted_overlap():
    source = '''
def output(is_first_chunk, is_final):
    if is_first_chunk:
        return 'first'
    elif not is_first_chunk and not is_final:
        return 'crossfade-final' if is_final else 'crossfade-middle'
    return 'replayed-overlap'
'''
    namespace = {}
    exec(compile(corrected_source(source, 'audio'), '<test>', 'exec'), namespace)
    assert namespace['output'](False, True) == 'crossfade-final'
    assert namespace['output'](False, False) == 'crossfade-middle'


def test_unknown_runtime_source_is_rejected():
    with pytest.raises(RuntimeError, match='Unsupported'):
        corrected_source('def changed(): pass', 'semantic')


def test_reference_cache_reuses_voices_and_invalidates_modified_files_and_weights(tmp_path):
    class Model:
        def __init__(self):
            self.prompt_cache = {}
            self.encodings = 0

        def init_t2s_weights(self, path):
            pass

        def init_vits_weights(self, path):
            pass

        def empty_cache(self):
            pass

    def run(model, request):
        if model.prompt_cache.get('ref_audio_path') != request['ref_audio_path']:
            model.encodings += 1
            model.prompt_cache = {'ref_audio_path': request['ref_audio_path'], 'refer_spec': [model.encodings]}
        yield model.prompt_cache['refer_spec'][0]

    install_reference_cache(Model, run)
    model = Model()
    paths = [tmp_path / f'{i}.wav' for i in range(10)]
    for path in paths:
        path.write_bytes(b'fixture')
    request = lambda index: {'ref_audio_path': str(paths[index]), 'prompt_text': 'one', 'prompt_lang': 'en'}
    assert list(model.run(request(0))) == [1]
    assert list(model.run(request(1))) == [2]
    assert list(model.run(request(0))) == [1]
    paths[0].write_bytes(b'changed fixture')
    assert list(model.run(request(0))) == [3]
    model.init_vits_weights('other-model')
    assert list(model.run(request(0))) == [4]
    for index in range(10):
        list(model.run(request(index)))
    assert len(model._voice_cache) == 8


def test_speaker_anchor_is_scoped_to_request_and_restored_on_close_or_error(tmp_path, monkeypatch):
    from app import gpt_sovits_runtime as runtime

    class Anchor:
        def clone(self):
            return 'accepted-anchor'

    class Speaker:
        def compute_embedding3(self, waveform):
            return waveform

    class Model:
        def __init__(self):
            self.prompt_cache = {}
            self.sv_model = Speaker()

        def init_t2s_weights(self, path): pass
        def init_vits_weights(self, path): pass
        def empty_cache(self): pass

    def run(model, request):
        yield model.sv_model.compute_embedding3('normal-reference')
        if request.get('fail'):
            raise ValueError('synthesis failed')

    monkeypatch.setattr(runtime, '_original_speaker_embedding', lambda *args: Anchor())
    install_reference_cache(Model, run)
    model = Model()
    path = tmp_path / 'original.wav'
    path.touch()
    anchored = {'speaker_ref_audio_path': str(path)}
    iterator = model.run(anchored)
    assert next(iterator) == 'accepted-anchor'
    iterator.close()
    assert list(model.run({})) == ['normal-reference']
    with pytest.raises(ValueError, match='synthesis failed'):
        list(model.run({**anchored, 'fail': True}))
    assert list(model.run({})) == ['normal-reference']


def test_fused_anchor_key_tracks_all_files_order_threshold_and_mode(tmp_path):
    from app.gpt_sovits_runtime import _speaker_anchor_key
    paths = [tmp_path/f'{i}.wav' for i in range(3)]
    for path in paths: path.write_bytes(b'original')
    first, second, third = map(str, paths)
    original = _speaker_anchor_key(first, [second, third], .85)
    assert original != _speaker_anchor_key(first, [third, second], .85)
    assert original != _speaker_anchor_key(first, [second, third], .88)
    assert _speaker_anchor_key(first) != _speaker_anchor_key(first, [])
    paths[2].write_bytes(b'new auxiliary content')
    assert original != _speaker_anchor_key(first, [second, third], .85)


@pytest.mark.parametrize('filename,method,kind', [
    ('AR/models/t2s_model.py', 'infer_panel_naive', 'semantic'),
    ('TTS_infer_pack/TTS.py', 'run', 'audio'),
])
def test_installed_upstream_source_matches_patch_contract(filename, method, kind):
    root = detect_gpt_sovits_root()
    path = root / 'GPT_SoVITS' / filename if root else None
    if path is None or not path.is_file():
        pytest.skip('Optional GPT-SoVITS runtime is not installed')
    module = ast.parse(path.read_text(encoding='utf-8'))
    function = next(node for node in ast.walk(module) if isinstance(node, ast.FunctionDef) and node.name == method)
    compile(corrected_source(ast.unparse(function), kind), '<contract>', 'exec')
