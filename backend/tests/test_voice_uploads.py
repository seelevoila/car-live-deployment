import array
import io
import math
from pathlib import Path
import wave

import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import settings
from app.db import conn, init_db


def test_ffmpeg_lookup_accepts_explicit_binary(monkeypatch, tmp_path):
    binary = tmp_path / "ffmpeg.exe"
    binary.touch()
    monkeypatch.setenv("FFMPEG_BIN", str(binary))
    assert main._ffmpeg_binary() == str(binary)


@pytest.fixture
def voice_upload_client(monkeypatch, tmp_path):
    if not main._ffmpeg_binary():
        pytest.skip("ffmpeg is required for reference conversion")
    monkeypatch.setattr(settings, "database_path", tmp_path / "voices.db")
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    # Exercise upload, conversion, quality checks and persistence without
    # making this API regression test depend on a running GPU model.
    monkeypatch.setattr(main, "_warm_single_voice", lambda voice_id: None)
    init_db()
    return TestClient(main.app)


@pytest.mark.parametrize("operation", ["analyze", "clone"])
def test_voice_upload_converts_stereo_recording(voice_upload_client, operation):
    sample_rate = 48000
    samples = array.array("h")
    for index in range(sample_rate * 5):
        value = int(7000 * math.sin(2 * math.pi * 220 * index / sample_rate))
        samples.extend((value, value))
    payload = io.BytesIO()
    with wave.open(payload, "wb") as audio:
        audio.setnchannels(2)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        audio.writeframes(samples.tobytes())
    response = voice_upload_client.post(
        f"/api/voices/{operation}",
        headers={"Origin": "http://127.0.0.1:5173"},
        data={"name": "上传转换测试", "prompt_text": "大家好，欢迎来到直播间，一起来了解今天的新车。"},
        files={"sample": ("recording.wav", payload.getvalue(), "audio/wav")},
    )
    assert response.status_code == 200, response.text
    assert response.headers["access-control-allow-origin"] == "*"
    body = response.json()
    assert body["quality"]["status"] == "ready"
    assert body["quality"]["channels"] == 1
    assert body["quality"]["sample_rate"] == 24000
    assert body["quality"]["sample_width"] == 2
    assert body['quality']['normalization']['after']['peak_db'] <= -2.95
    assert body['quality']['normalization']['rms_change_db'] is not None
    if operation == "clone":
        with conn() as database:
            voice = database.execute("SELECT * FROM voices WHERE id=?", (body["id"],)).fetchone()
        assert voice["synthesis_status"] == "pending"
        assert voice['prompt_policy'] == 'checked'
        assert Path(voice["reference_path"]).is_file()
    else:
        assert not list((settings.upload_dir / "voice-staging").iterdir())


def test_invalid_voice_recording_returns_readable_error(voice_upload_client):
    response = voice_upload_client.post(
        "/api/voices/clone",
        headers={"Origin": "http://127.0.0.1:5173"},
        data={"prompt_text": "这是参考录音中的实际文字。"},
        files={"sample": ("broken.wav", b"not an audio file" * 2048, "audio/wav")},
    )
    assert response.status_code == 422
    assert response.headers["access-control-allow-origin"] == "*"
    assert "参考音频无法解码" in response.json()["detail"]
    assert not list((settings.upload_dir / "voices").iterdir())


def _recording():
    samples = array.array('h', (int(3000*math.sin(2*math.pi*220*i/24000)) for i in range(24000*5)))
    payload = io.BytesIO()
    with wave.open(payload, 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(samples.tobytes())
    return payload.getvalue()


def test_two_recordings_keep_their_corresponding_transcripts(voice_upload_client):
    audio = _recording()
    response = voice_upload_client.post('/api/voices/clone',
        data={'prompt_text':'大家好，欢迎来到直播间。', 'aux_prompt_texts':['一起看看这款车的续航表现。']},
        files=[('sample',('main.wav',audio,'audio/wav')),('aux_samples',('aux.wav',audio,'audio/wav'))])
    assert response.status_code == 200, response.text
    assert response.json()['reference_count'] == 2
    import json
    with conn() as database:
        voice=database.execute('SELECT * FROM voices WHERE id=?',(response.json()['id'],)).fetchone()
    assert json.loads(voice['aux_prompt_texts']) == ['一起看看这款车的续航表现。']
    assert Path(json.loads(voice['aux_reference_paths'])[0]).is_file()


def test_invalid_auxiliary_leaves_no_primary_or_derivative_files(voice_upload_client):
    response=voice_upload_client.post('/api/voices/clone',data={'prompt_text':'大家好，欢迎来到直播间。'},
        files=[('sample',('main.wav',_recording(),'audio/wav')),('aux_samples',('aux.txt',b'broken','text/plain'))])
    assert response.status_code == 400
    assert not list((settings.upload_dir/'voices').iterdir())


@pytest.mark.parametrize('error',[OSError('cannot start ffmpeg'),main.subprocess.TimeoutExpired('ffmpeg',45)])
def test_level_probe_failure_is_readable_and_cleans_upload(voice_upload_client,monkeypatch,error):
    def failed(*args,**kwargs): raise error
    monkeypatch.setattr(main.subprocess,'run',failed)
    response=voice_upload_client.post('/api/voices/clone',headers={'Origin':'http://127.0.0.1:5173'},
        data={'prompt_text':'大家好，欢迎来到直播间。'},files={'sample':('main.wav',_recording(),'audio/wav')})
    assert response.status_code == 422
    assert response.headers['access-control-allow-origin']=='*'
    assert '电平检测失败' in response.json()['detail']
    assert not list((settings.upload_dir/'voices').iterdir())
