import hashlib
import shutil
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import main, preset_voices
from app.config import settings
from app.db import conn, init_db


@pytest.fixture
def clean_catalog(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'database_path', tmp_path / 'fresh.db')
    monkeypatch.setattr(settings, 'upload_dir', tmp_path / 'empty-uploads')
    monkeypatch.setattr(settings, 'gpt_sovits_ref_audio', '')
    monkeypatch.setattr(settings, 'gpt_sovits_prompt_text', '')
    # Verify the package resolves on a different machine/path without uploads.
    destination = tmp_path / 'relocated' / 'preset_voices'
    shutil.copytree(preset_voices.PRESET_DIR, destination)
    monkeypatch.setattr(preset_voices, 'PRESET_DIR', destination)
    init_db()
    return TestClient(main.app)


def test_new_install_has_three_distinct_ready_speakers(clean_catalog):
    voices = clean_catalog.get('/api/voices').json()
    builtin = [voice for voice in voices if voice['builtin']]
    assert len(builtin) == 3
    assert [v['id'] for v in voices[:3]] == list(preset_voices.PRESET_VOICES)
    assert not any(voice['cloned'] for voice in voices)
    hashes = set()
    for voice in builtin:
        assert voice['quality']['status'] == 'ready'
        assert voice['kind'] == 'builtin' and not voice['editable']
        path, text, language = main._voice_config(voice['id'])
        assert Path(path).parent == preset_voices.PRESET_DIR
        assert text and language == 'zh'
        hashes.add(hashlib.sha256(Path(path).read_bytes()).hexdigest())
        for asset, path in zip(preset_voices.PRESET_VOICES[voice['id']]['assets'], main.preset_reference_paths(voice['id'])):
            assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == asset['sha256']
    assert len(hashes) == 3


def test_clone_edit_and_delete_do_not_change_builtin(clean_catalog):
    before = main._tts_params(main.TTSRequest(text='续航580公里。', voice_id='steady'))
    clone = settings.upload_dir / 'clone.wav'
    shutil.copyfile(before['ref_audio_path'], clone)
    with conn() as c:
        c.execute("INSERT INTO voices(id,name,provider,reference_path,prompt_text) VALUES(?,?,?,?,?)",
                  ('clone', '我的克隆', 'gpt-sovits', str(clone), '测试参考文字。'))
    assert clean_catalog.patch('/api/voices/clone', json={'name': '改名后的克隆'}).status_code == 200
    assert clean_catalog.delete('/api/voices/clone').status_code == 200
    assert not clone.exists()
    after = main._tts_params(main.TTSRequest(text='续航580公里。', voice_id='steady'))
    assert before == after


@pytest.mark.parametrize('voice_id', list(preset_voices.PRESET_VOICES))
def test_builtin_is_protected_from_clone_mutations(clean_catalog, voice_id):
    assert clean_catalog.patch('/api/voices/' + voice_id, json={'prompt_text': '替换原文。'}).status_code == 403
    assert clean_catalog.delete('/api/voices/' + voice_id).status_code == 403
    assert clean_catalog.post('/api/voices/' + voice_id + '/optimize').status_code == 403
    assert main._calibrate_voice(voice_id) is None
    main._schedule_voice_calibration(voice_id)
    assert voice_id not in main.VOICE_CALIBRATION_QUEUE


def test_missing_builtin_does_not_fall_back_to_another_speaker(clean_catalog):
    Path(main.preset_reference_paths('steady')[0]).unlink()
    with pytest.raises(HTTPException) as caught:
        main._voice_config('steady')
    assert caught.value.status_code == 503
    assert main._voice_config('friendly')[0].endswith('friendly-0.wav')


def test_legacy_install_migrates_without_changing_uploaded_clones(clean_catalog):
    with conn() as c:
        c.execute("INSERT INTO voices(id,name,reference_path,prompt_text) VALUES('original','原音色','old.wav','原文。')")
        c.execute("UPDATE voices SET reference_voice_id='original', reference_path='', name='沉稳主播' WHERE id='steady'")
    init_db()
    init_db()
    with conn() as c:
        builtin = c.execute("SELECT name,reference_path,reference_voice_id FROM voices WHERE id='steady'").fetchone()
        clone = c.execute("SELECT name,reference_path,prompt_text FROM voices WHERE id='original'").fetchone()
    assert tuple(clone) == ('原音色', 'old.wav', '原文。')
    assert builtin['name'] == '沉稳阿川' and builtin['reference_voice_id'] == ''
    assert Path(builtin['reference_path']).is_file()
