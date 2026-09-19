import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from app import main
from app.config import settings
from app.db import conn, init_db
from app.tts_gpt_sovits import model_profiles, profile_weights, GptSovitsEngine


def test_custom_voice_model_does_not_change_other_speakers(tmp_path, monkeypatch):
    manifest = tmp_path / 'profiles.json'
    manifest.write_text(json.dumps({'custom-voice': {'gpt_weights': 'gpt.ckpt',
        'sovits_weights': 'voice.pth', 'speaker_ref_audio_path': 'original.wav'}}))
    monkeypatch.setattr(settings, 'gpt_sovits_profiles_file', manifest)
    monkeypatch.setattr(settings, 'database_path', tmp_path / 'voices.db')
    monkeypatch.setattr(settings, 'upload_dir', tmp_path / 'uploads')
    init_db()
    with conn() as c:
        c.execute("INSERT INTO voices(id,reference_path,model_profile,prompt_policy) VALUES('target','a.wav','custom-voice','checked')")
        c.execute("INSERT INTO voices(id,reference_path,model_profile) VALUES('other','b.wav','base')")
    monkeypatch.setattr(main, '_voice_config', lambda _: ('a.wav', '准确的参考原文。', 'zh'))
    params = main._live_unit_params(main.TTSRequest(voice_id='target', text='今天介绍这款车。'), 0)
    assert params['speaker_ref_audio_path'] == str(tmp_path / 'original.wav')
    assert params['prompt_text'] == '准确的参考原文。'
    assert main._voice_model_profile('target') == 'custom-voice'
    for other in ('other', 'steady', 'energetic', 'friendly'):
        assert main._voice_model_profile(other) == 'base'
        assert 'speaker_ref_audio_path' not in main._tts_params(main.TTSRequest(voice_id=other, text='你好。'))
    manifest.write_text('{}')
    with pytest.raises(main.HTTPException, match='模型配置缺失'):
        main._voice_model_profile('target')


def test_sync_and_async_profile_switch_transport(tmp_path):
    paths = {n: tmp_path / n for n in ('gpt.ckpt', 'base.pth', 'custom.pth')}
    for p in paths.values():
        p.touch()
    manifest = tmp_path / 'profiles.json'
    manifest.write_text(json.dumps({'custom': {'gpt_weights': 'gpt.ckpt', 'sovits_weights': 'custom.pth'}}))
    cfg = SimpleNamespace(gpt_sovits_profiles_file=manifest, gpt_sovits_url='http://model',
        gpt_sovits_base_gpt_weights=str(paths['gpt.ckpt']), gpt_sovits_base_sovits_weights=str(paths['base.pth']),
    )
    calls = []

    def serve(request):
        if request.url.path == '/runtime/status':
            return httpx.Response(200, json={})
        calls.append((request.url.path, request.url.params['weights_path']))
        return httpx.Response(200, json={'ok': True})

    transport = httpx.MockTransport(serve)
    with httpx.Client(transport=transport) as client:
        GptSovitsEngine.load_weights(cfg, 'custom', client)
        GptSovitsEngine.load_weights(cfg, 'base', client)
    async def switch():
        async with httpx.AsyncClient(transport=transport) as client:
            await GptSovitsEngine.load_weights_async(cfg, 'custom', client)
            await GptSovitsEngine.load_weights_async(cfg, 'base', client)
    asyncio.run(switch())
    assert calls[:4] == calls[4:]
    assert calls[1][1] == str(paths['custom.pth'])
    assert calls[3][1] == str(paths['base.pth'])
    assert profile_weights(cfg, 'base')[1] == str(paths['base.pth'])
    manifest.write_text(json.dumps({'base': {'gpt_weights': 'gpt.ckpt', 'sovits_weights': 'custom.pth'}}))
    with pytest.raises(RuntimeError, match='profile name'):
        model_profiles(cfg)


def test_fusion_is_explicit_per_profile_and_paths_resolve(tmp_path, monkeypatch):
    manifest = tmp_path/'profiles.json'
    monkeypatch.setattr(settings, 'gpt_sovits_profiles_file', manifest)
    profile = {'gpt_weights':'gpt.ckpt', 'sovits_weights':'sovits.pth',
               'speaker_ref_audio_path':'main.wav', 'speaker_aux_ref_audio_paths':['a.wav','b.wav']}
    manifest.write_text(json.dumps({'fusion':profile}))
    entry = model_profiles(settings)['fusion']
    assert entry['speaker_aux_ref_audio_paths'] == [str(tmp_path/'a.wav'), str(tmp_path/'b.wav')]
    assert 'speaker_aux_ref_audio_paths' not in model_profiles(settings)['base']
    manifest.write_text(json.dumps({'fusion':dict(profile, speaker_aux_ref_audio_paths='wrong.wav')}))
    with pytest.raises(RuntimeError, match='auxiliary paths'):
        model_profiles(settings)
