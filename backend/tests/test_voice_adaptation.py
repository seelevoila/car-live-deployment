import asyncio
import json
from contextlib import nullcontext
from pathlib import Path

import httpx
import pytest

from app import main, voice_adaptation as jobs
from app.config import settings
from app.db import conn, init_db
from app.runtime_serialization import ModelLeaseMiddleware
from app.short_adaptation import atomic_json, sha256
from app.tts_gpt_sovits import model_profiles


@pytest.fixture
def voices(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'database_path', tmp_path / 'voices.db')
    monkeypatch.setattr(settings, 'upload_dir', tmp_path / 'uploads')
    monkeypatch.setattr(settings, 'gpt_sovits_profiles_file', tmp_path / 'models/profiles.json')
    monkeypatch.setattr(settings, 'gpt_sovits_base_sovits_weights', str(tmp_path / 'base.pth'))
    monkeypatch.setattr(settings, 'gpt_sovits_url', 'http://runtime')
    monkeypatch.setattr(settings, 'tts_provider', 'gpt-sovits')
    (tmp_path / 'base.pth').write_bytes(b'official base')
    init_db()
    for voice_id in ('one', 'two'):
        source = tmp_path / (voice_id + '.wav')
        source.write_bytes(voice_id.encode())
        with conn() as c:
            c.execute("INSERT INTO voices(id,reference_path,prompt_text,prompt_lang,model_profile,prompt_policy) VALUES(?,?,?,'zh','base','checked')",
                      (voice_id, str(source), '欢迎来到直播间。'))
    main.LIVE_PATH_WARMED.set()
    monkeypatch.setattr(main, '_ACTIVE_MODEL_PROFILE', 'base')
    monkeypatch.setattr(main, '_tts_lock', lambda **kw: nullcontext())
    monkeypatch.setattr(main, '_ensure_model_profile_loaded', lambda *a: None)
    monkeypatch.setattr(main, '_mark_tts_success', lambda: None)
    yield tmp_path
    jobs.BUSY.clear()
    main.LIVE_PATH_WARMED.clear()
    main.VOICE_WARMED.difference_update({'one', 'two'})


def enqueue(voice_id):
    with conn() as c:
        return jobs.enqueue(c, voice_id)


def test_inputs_use_own_originals_and_only_transcribed_auxiliaries(voices):
    normalized = voices / 'one.normalized.wav'
    normalized.write_bytes(b'derivative')
    with conn() as c:
        c.execute('UPDATE voices SET reference_path=?,aux_reference_paths=?,aux_prompt_texts=? WHERE id=?',
                  (str(normalized), json.dumps([str(voices / 'two.wav')]), '[""]', 'one'))
        row = c.execute("SELECT * FROM voices WHERE id='one'").fetchone()
    records, signature, omitted = jobs.training_inputs(row)
    assert records[0]['audio'] == str(voices / 'one.wav')
    assert len(records) == 1 and omitted == 1
    (voices / 'one.wav').write_bytes(b'changed source')
    assert jobs.training_inputs(row)[1] != signature


def test_atomic_enqueue_edit_guard_and_restart_failure(voices):
    job = enqueue('one')
    with pytest.raises(main.HTTPException, match='训练'):
        jobs.assert_editable('one')
    with pytest.raises(main.HTTPException):
        main.delete_voice('one')
    jobs._state('one', job, 'running', 'training')
    jobs.recover()
    assert jobs.get_job('one')['status'] == 'failed'
    with conn() as c:
        assert c.execute("SELECT model_profile FROM voices WHERE id='one'").fetchone()[0] == 'base'
    jobs.rollback('one')
    assert jobs.get_job('one')['status'] == 'rolled_back'
    assert enqueue('one') != job


def setup_runtime(monkeypatch, job_id, tmp_path, *, corrupt=False, fail=False):
    checkpoint = tmp_path / 'models/adaptations' / job_id / 'acoustic.pth'
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_bytes(job_id.encode())
    seen = []
    def serve(request):
        seen.append(request.url.path)
        if request.url.path == '/runtime/adapt':
            if fail:
                return httpx.Response(500, text='nonfinite gradient')
            return httpx.Response(200, json={'completed': True, 'effective_steps': 8,
                'skipped_generator_steps': 0, 'skipped_discriminator_steps': 0, 'frozen_tensors_changed': [],
                'checkpoint': str(checkpoint), 'sha256': 'wrong' if corrupt else sha256(checkpoint),
                'initial_sha256': sha256(tmp_path / 'base.pth')})
        if request.url.path == '/runtime/status':
            return httpx.Response(200, json={'sovits_weights': str(checkpoint)})
        return httpx.Response(200, content=b'audio')
    real_client = httpx.Client
    monkeypatch.setattr(jobs.httpx, 'Client', lambda **kw: real_client(transport=httpx.MockTransport(serve)))
    monkeypatch.setattr(main, '_live_unit_params', lambda *a: {'text': '欢迎来到直播间。', 'seed': 3})
    monkeypatch.setattr(main, '_probe_audio_payload', lambda *a, **kw: {'status': 'ready', 'duration': 2.})
    async def check(*args):
        assert jobs.BUSY.is_set()
        with conn() as c:
            assert c.execute("SELECT model_profile FROM voices WHERE id='one'").fetchone()[0] == 'base'
        return b'accepted-audio', {'ok': True, 'cache_hit': False}
    monkeypatch.setattr(main.prompt_guard, 'checked_sentence', check)
    return seen


@pytest.mark.parametrize('failure', ['transport', 'hash', 'probe', 'stale'])
def test_failed_or_stale_job_never_promotes_and_can_retry(voices, monkeypatch, failure):
    job = enqueue('one')
    seen = setup_runtime(monkeypatch, job, voices, corrupt=failure == 'hash', fail=failure == 'transport')
    if failure == 'probe':
        async def bad_probe(*a): return None, {'ok': False}
        monkeypatch.setattr(main.prompt_guard, 'checked_sentence', bad_probe)
    if failure == 'stale':
        with conn() as c:
            c.execute("UPDATE voices SET prompt_text='已经改过参考原文。' WHERE id='one'")
    assert jobs.run_pending('one')
    assert jobs.get_job('one')['status'] == 'failed'
    with conn() as c:
        assert c.execute("SELECT model_profile FROM voices WHERE id='one'").fetchone()[0] == 'base'
    assert not jobs.BUSY.is_set()
    if failure == 'stale':
        assert '/runtime/adapt' not in seen
    assert enqueue('one') != job


def test_success_promotes_only_own_voice_and_rollback_retains_artifact(voices, monkeypatch):
    with conn() as c:
        before = dict(c.execute("SELECT * FROM voices WHERE id='two'").fetchone())
    job = enqueue('one')
    setup_runtime(monkeypatch, job, voices)
    jobs.run_pending('one')
    assert jobs.get_job('one')['status'] == 'complete'
    with conn() as c:
        assert c.execute("SELECT model_profile FROM voices WHERE id='one'").fetchone()[0] == 'adapt-' + job
        assert dict(c.execute("SELECT * FROM voices WHERE id='two'").fetchone()) == before
    installed = model_profiles(settings)['adapt-' + job]
    assert installed['speaker_ref_audio_path'] == str(voices / 'one.wav')
    assert 'speaker_aux_ref_audio_paths' not in installed
    jobs.rollback('one')
    assert Path(installed['sovits_weights']).is_file()
    with conn() as c:
        assert c.execute("SELECT model_profile FROM voices WHERE id='one'").fetchone()[0] == 'base'


def test_failure_restoring_resident_voice_revokes_promotion_and_ready(voices, monkeypatch):
    job = enqueue('one')
    setup_runtime(monkeypatch, job, voices)
    def load(profile, client):
        if profile == 'base':
            assert jobs.get_job('one')['status'] == 'validating'
            with conn() as c:
                assert c.execute("SELECT model_profile,synthesis_status FROM voices WHERE id='one'").fetchone()[:] == ('base', 'pending')
            raise RuntimeError('restore failed')
    monkeypatch.setattr(main, '_ensure_model_profile_loaded', load)
    jobs.run_pending('one')
    assert jobs.get_job('one')['status'] == 'failed'
    assert not main.LIVE_PATH_WARMED.is_set() and not jobs.BUSY.is_set()
    with conn() as c:
        assert c.execute("SELECT model_profile FROM voices WHERE id='one'").fetchone()[0] == 'base'


def test_training_waits_for_live_session_without_holding_gpu(voices, monkeypatch):
    from app.db import now
    with conn() as c:
        c.execute("INSERT INTO sessions(id,status,updated_at) VALUES('live','playing',?)", (now(),))
    assert jobs.live_session_active()
    with pytest.raises(RuntimeError, match='直播仍在播报'):
        jobs.wait_for_live_idle(timeout=0)
    assert not jobs.BUSY.is_set()
    with conn() as c:
        c.execute("UPDATE sessions SET status='stopped' WHERE id='live'")
    jobs.wait_for_live_idle(timeout=0)


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.mark.anyio
async def test_runtime_lease_includes_stream_tail_but_not_health():
    first = asyncio.Event()
    release = asyncio.Event()
    visited = []
    async def application(scope, receive, send):
        visited.append(scope['path'])
        if scope['path'] == '/tts':
            first.set()
            await release.wait()
    app = ModelLeaseMiddleware(application)
    task = asyncio.create_task(app({'type': 'http', 'path': '/tts'}, None, None))
    await first.wait()
    training = asyncio.create_task(app({'type': 'http', 'path': '/runtime/adapt'}, None, None))
    await app({'type': 'http', 'path': '/runtime/status'}, None, None)
    await asyncio.sleep(0)
    assert visited == ['/tts', '/runtime/status']
    release.set()
    await asyncio.gather(task, training)
    assert visited[-1] == '/runtime/adapt'
