import json
from pathlib import Path
import pytest
from app import main

CASES = json.loads((Path(__file__).resolve().parents[2] / 'data/testset/speech_normalization.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('case', CASES)
def test_speech_contract_and_repeated_normalization(case):
    assert main.normalize_tts_text(case['input']) == case['expected']
    assert main.normalize_tts_text(case['expected']) == case['expected']


def test_percent_prefix_and_value_stay_in_the_same_phrase():
    text = '这段说明需要保持连贯接下来介绍电池电量范围从百分之三十到百分之八十然后继续介绍配置。'
    for token in ['百分之三十', '百分之八十']:
        start = text.index(token)
        for limit in range(start+1, start+len(token)):
            cut = main._safe_tts_cut(text, limit)
            assert cut <= start or cut >= start+len(token)


@pytest.mark.parametrize('unitized', [False, True])
def test_direct_api_and_browser_phrases_clean_speech_before_splitting(unitized):
    source = '从30%充到80%需要0.33小时[2]。'
    units = main._tts_stream_units(main.TTSRequest(text=source, unitized=unitized))
    assert ''.join(units) == '从百分之三十充到百分之八十需要零点三三小时。'


def test_preview_and_stream_send_clean_text_but_keep_voice_reference(monkeypatch):
    monkeypatch.setattr(main, '_voice_config', lambda _: ('ref.wav','参考声音30%。','zh'))
    monkeypatch.setattr(main, '_voice_aux_reference_paths', lambda _: [])
    request = main.TTSRequest(text='电量30%[1]。')
    for params in [main._tts_params(request), main._live_unit_params(request, 0)]:
        assert params['text'] == '电量百分之三十。'
        assert params['prompt_text'] == '参考声音30%。'


def test_live_stream_batch_is_sent_as_one_normalized_upstream_request():
    request = main.TTSRequest(
        text='第一句介绍续航30%，第二句介绍激光雷达[2]。',
        unitized=True,
        stream_batch=True,
    )
    assert main._tts_stream_units(request) == [
        '第一句介绍续航百分之三十，第二句介绍激光雷达。'
    ]


def test_live_clone_natural_delivery_preserves_sampling_without_boosting_temperature(monkeypatch):
    monkeypatch.setattr(main.settings, 'gpt_sovits_live_delivery', 'natural')
    monkeypatch.setattr(main, '_voice_config', lambda _voice_id: ('ref.wav', '参考文本。', 'zh'))
    monkeypatch.setattr(main, '_voice_aux_reference_paths', lambda _voice_id: [])
    monkeypatch.setattr(main, '_voice_sampling_profile', lambda _voice_id: {
        'top_k': 25, 'top_p': 0.95, 'temperature': 0.92, 'repetition_penalty': 1.35,
    })
    live = main._tts_params(main.TTSRequest(text='测试', voice_id='clone'), streaming=True)
    preview = main._tts_params(main.TTSRequest(text='测试', voice_id='clone'), streaming=False)
    assert live['top_k'] == 25
    assert live['top_p'] == 0.95
    assert live['temperature'] == 0.92
    assert preview['top_k'] == 25
    assert preview['top_p'] == 0.95
    assert preview['temperature'] == 0.92


def test_live_clone_seed_is_fixed_across_sentences_by_default(monkeypatch):
    monkeypatch.setattr(main.settings, 'gpt_sovits_live_seed_mode', 'fixed')
    monkeypatch.setattr(main, '_voice_config', lambda _voice_id: ('ref.wav', '参考文本。', 'zh'))
    monkeypatch.setattr(main, '_voice_aux_reference_paths', lambda _voice_id: [])
    first = main._tts_params(main.TTSRequest(text='第一句。', voice_id='clone'), streaming=True)
    second = main._tts_params(main.TTSRequest(text='第二句。', voice_id='clone'), streaming=True)
    retry = main._tts_params(main.TTSRequest(text='第一句。', voice_id='clone'), streaming=True)
    assert first['seed'] == second['seed']
    assert first['seed'] == retry['seed']
    assert main._tts_params(main.TTSRequest(text='第一句。', voice_id='clone'), streaming=False)['seed'] == main._voice_sampling_seed('clone')
