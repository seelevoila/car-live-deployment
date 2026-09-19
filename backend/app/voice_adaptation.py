"""Durable per-voice adaptation jobs; existing voices are never auto-migrated."""
import hashlib
import json
from pathlib import Path
import threading
import time
from uuid import uuid4

import httpx
from fastapi import HTTPException

from .config import settings
from .db import conn, now
from .short_adaptation import atomic_json, sha256

BUSY = threading.Event()
ACTIVE = {'queued', 'running', 'validating'}


def get_job(voice_id):
    with conn() as c:
        row = c.execute('SELECT * FROM voice_adaptations WHERE voice_id=?', (voice_id,)).fetchone()
    if not row:
        return None
    result = dict(row)
    result['report'] = json.loads(result['report'])
    return result


def assert_editable(voice_id):
    job = get_job(voice_id)
    if job and job['status'] in ACTIVE:
        raise HTTPException(409, '该音色正在排队、训练或验收，请完成后再修改或删除')


def live_session_active():
    # Browsers update the current sentence while playing. Expire abandoned
    # tabs rather than letting a stale database session block all new clones.
    with conn() as c:
        return c.execute("SELECT 1 FROM sessions WHERE status='playing' "
                         "AND julianday(updated_at)>julianday('now','-60 seconds') LIMIT 1").fetchone() is not None


def wait_for_live_idle(timeout=180):
    deadline = time.monotonic() + timeout
    while live_session_active():
        if time.monotonic() >= deadline:
            raise RuntimeError('直播仍在播报，专属训练未启动；请空闲后重试')
        time.sleep(1)


def training_inputs(row):
    from .main import _original_reference_audio
    main = str(_original_reference_audio(Path(row['reference_path'])).resolve())
    records = [{'audio': main, 'transcript': row['prompt_text'], 'language': row['prompt_lang'] or 'zh'}]
    auxiliaries = json.loads(row['aux_reference_paths'] or '[]')
    prompts = json.loads(row['aux_prompt_texts'] or '[]')
    for path, prompt in zip(auxiliaries, prompts):
        if len(prompt.strip()) >= 4:
            records.append({'audio': str(_original_reference_audio(Path(path)).resolve()),
                            'transcript': prompt, 'language': row['prompt_lang'] or 'zh'})
    # Include all source fields: even an omitted auxiliary or changed policy
    # invalidates stale work; it must never be silently installed later.
    identity = {key: row[key] for key in ('reference_path', 'prompt_text', 'prompt_lang',
                                         'aux_reference_paths', 'aux_prompt_texts', 'prompt_policy')}
    identity['recordings'] = [{**item, 'sha256': sha256(item['audio'])} for item in records]
    signature = hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return records, signature, len(auxiliaries) - (len(records) - 1)


def enqueue(c, voice_id):
    """Called inside the voice INSERT transaction, so no orphan pending clone."""
    row = c.execute('SELECT * FROM voices WHERE id=?', (voice_id,)).fetchone()
    old = c.execute('SELECT * FROM voice_adaptations WHERE voice_id=?', (voice_id,)).fetchone()
    if old and old['status'] in ACTIVE:
        raise HTTPException(409, '音色专属训练已在队列中')
    records, signature, omitted = training_inputs(row)
    if any(not item['transcript'].strip() for item in records):
        raise HTTPException(422, '训练需要与录音逐字一致的原文')
    if row['prompt_lang'] not in {'zh', 'en', 'ja', 'ko', 'yue'}:
        raise HTTPException(422, '当前语言暂不支持短时适配')
    job_id = uuid4().hex
    message = '专属音色训练已排队；训练目标约 30 秒，排队和合成验收另计'
    c.execute('INSERT OR REPLACE INTO voice_adaptations VALUES(?,?,?,?,?,?,?,?,?)',
              (voice_id, job_id, 'queued', message, row['model_profile'] or 'base', signature,
               now(), now(), json.dumps({'omitted_aux_without_transcript': omitted})))
    c.execute("UPDATE voices SET synthesis_status='pending',synthesis_message=? WHERE id=?", (message, voice_id))
    return job_id


def _state(voice_id, job_id, status, message, report=None):
    with conn() as c:
        c.execute('UPDATE voice_adaptations SET status=?,message=?,updated_at=?,report=COALESCE(?,report) '
                  'WHERE voice_id=? AND job_id=?',
                  (status, message[:500], now(), json.dumps(report, ensure_ascii=False) if report is not None else None,
                   voice_id, job_id))
        if status in ACTIVE or status == 'failed':
            c.execute('UPDATE voices SET synthesis_status=?,synthesis_message=? WHERE id=?',
                      ('failed' if status == 'failed' else 'pending', message[:500], voice_id))


def recover():
    """Interrupted jobs fail visibly; retries always get a fresh output directory."""
    from . import main
    with conn() as c:
        jobs = [dict(row) for row in c.execute("SELECT * FROM voice_adaptations WHERE status IN ('queued','running','validating')")]
    for job in jobs:
        if job['status'] == 'queued':
            threading.Thread(target=main._warm_single_voice, args=(job['voice_id'],), daemon=True).start()
        else:
            _state(job['voice_id'], job['job_id'], 'failed', '服务重启中断了专属训练；未切换权重，可重试或恢复原版')


def run_pending(voice_id):
    """Return True when adaptation owns (or has failed) the clone lifecycle."""
    from . import main
    job = get_job(voice_id)
    if not job or job['status'] not in ACTIVE | {'failed'}:
        return False
    if job['status'] != 'queued':
        return True
    job_id = job['job_id']
    started = time.perf_counter()
    report = dict(job['report'])
    previous_active = None
    try:
        # Startup live warmup must finish first. Normal foreground playback
        # retains scheduler priority while this background job is queued.
        if not main.LIVE_PATH_WARMED.wait(timeout=90):
            raise RuntimeError('播报服务尚未就绪，未启动训练')
        wait_for_live_idle()
        with main._tts_lock(priority='background', timeout=180):
            if live_session_active():
                raise RuntimeError('直播已开始播报，专属训练未启动；请空闲后重试')
            with conn() as c:
                claimed = c.execute("UPDATE voice_adaptations SET status='running',updated_at=? "
                                    "WHERE voice_id=? AND job_id=? AND status='queued'", (now(), voice_id, job_id)).rowcount
            if not claimed:
                return True
            BUSY.set()
            previous_active = main._ACTIVE_MODEL_PROFILE
            try:
                with httpx.Client(timeout=httpx.Timeout(180, connect=5), trust_env=False) as client:
                    with conn() as c:
                        row = c.execute('SELECT * FROM voices WHERE id=?', (voice_id,)).fetchone()
                    records, signature, _ = training_inputs(row)
                    if signature != job['source_signature']:
                        raise RuntimeError('参考素材已变化，旧任务未安装')
                    _state(voice_id, job_id, 'running', '正在使用此音色自己的录音训练专属声学权重')
                    base_url = settings.gpt_sovits_url.rstrip('/').removesuffix('/tts')
                    report['queue_seconds'] = time.perf_counter() - started
                    response = client.post(base_url + '/runtime/adapt', json={
                        'job_id': job_id, 'records': records, 'seconds': settings.gpt_sovits_adaptation_seconds,
                        'max_steps': settings.gpt_sovits_adaptation_max_steps})
                    if not response.is_success:
                        raise RuntimeError(response.text[:400])
                    result = response.json()
                    report['training'] = result
                    checkpoint = (Path(settings.gpt_sovits_profiles_file).parent / 'adaptations' / job_id / 'acoustic.pth').resolve()
                    if (not result.get('completed') or result.get('effective_steps', 0) <= 0
                            or result.get('skipped_generator_steps') != 0 or result.get('skipped_discriminator_steps') != 0
                            or result.get('frozen_tensors_changed') != []
                            or Path(result.get('checkpoint', '')).resolve() != checkpoint
                            or result.get('sha256') != sha256(checkpoint)
                            or result.get('initial_sha256') != sha256(settings.gpt_sovits_base_sovits_weights)):
                        raise RuntimeError('训练产物或通用底模校验失败，未绑定音色')
                    profile_name = 'adapt-' + job_id
                    profile = {'gpt_weights': settings.gpt_sovits_base_gpt_weights,
                               'sovits_weights': str(checkpoint), 'speaker_ref_audio_path': records[0]['audio']}
                    # One immutable manifest per job avoids rewriting any
                    # existing speaker's registry entry or checkpoint.
                    atomic_json(checkpoint.parent / 'profile.json', {profile_name: profile})
                    _state(voice_id, job_id, 'validating', '专属权重已生成，正在逐句检查实际合成音频', report)
                    main._ACTIVE_MODEL_PROFILE = None
                    main._ensure_model_profile_loaded(profile_name, client)
                    status = client.get(base_url + '/runtime/status').json()
                    if Path(status.get('sovits_weights', '')).resolve() != checkpoint:
                        raise RuntimeError('运行时未加载新权重')
                    report['loaded_sovits_weights'] = status['sovits_weights']
                    params = main._live_unit_params(main.TTSRequest(text=main.CLONE_VALIDATION_TEXT, voice_id=voice_id), 0)
                    params.update(speaker_ref_audio_path=records[0]['audio'])
                    params.pop('speaker_aux_ref_audio_paths', None)

                    payload, check = main._checked_voice_probe(client, params, [profile_name, result['sha256']])
                    report['acceptance'] = check
                    if not payload:
                        raise RuntimeError('专属权重未通过实际人声验收，原权重绑定保持不变')
                    (checkpoint.parent / 'acceptance.wav').write_bytes(payload)
                    probe = main._probe_audio_payload(payload, expected_text=params['text'])
                    ready_message = ('专属权重已通过合成检查；本次触发重试或原文回退，播报可能等待较久，请试听'
                                     if check.get('prompt_retry_count') or check.get('fallback_without_prompt')
                                     else '专属权重已通过合成检查；相似度请试听确认')
                    report['profile'] = profile_name
            finally:
                # Restore the previously selected live voice before releasing
                # the backend lease. Never leave the trainer's last speaker
                # globally active while claiming a different cached profile.
                main._ACTIVE_MODEL_PROFILE = None
                if previous_active:
                    try:
                        with httpx.Client(timeout=60, trust_env=False) as restore_client:
                            main._ensure_model_profile_loaded(previous_active, restore_client)
                    except Exception:
                        main.LIVE_PATH_WARMED.clear()
                        raise
                BUSY.clear()
            # Publish readiness only after restoring the prior live profile.
            # Otherwise a UI may report completion several seconds before the
            # GPU lease is usable, and upload-to-ready measurements undercount.
            report['worker_seconds'] = time.perf_counter() - started
            report['includes_previous_profile_restoration'] = True
            atomic_json(checkpoint.parent / 'acceptance.json', report)
            with conn() as c:
                current = c.execute('SELECT * FROM voices WHERE id=?', (voice_id,)).fetchone()
                if not current or training_inputs(current)[1] != signature or current['model_profile'] != job['previous_profile']:
                    raise RuntimeError('音色已修改，旧任务未安装')
                c.execute("UPDATE voices SET model_profile=?,synthesis_status='ready',synthesis_message=?,"
                          'synthesis_duration=?,synthesis_checked_at=? WHERE id=?',
                          (profile_name, ready_message, probe['duration'], now(), voice_id))
                c.execute("UPDATE voice_adaptations SET status='complete',message=?,updated_at=?,report=? WHERE voice_id=? AND job_id=?",
                          (ready_message, now(), json.dumps(report, ensure_ascii=False), voice_id, job_id))
            main.VOICE_WARMED.add(voice_id)
            main._mark_tts_success()
    except Exception as exc:
        report.update(error=f'{type(exc).__name__}: {exc}', worker_seconds=time.perf_counter() - started)
        with conn() as c:
            c.execute('UPDATE voices SET model_profile=? WHERE id=? AND model_profile=?',
                      (job['previous_profile'], voice_id, 'adapt-' + job_id))
        _state(voice_id, job_id, 'failed', '专属训练失败：' + str(exc)[:320] + '；可重试或恢复原版', report)
        main.VOICE_WARMED.discard(voice_id)
        BUSY.clear()
    return True


def rollback(voice_id):
    """Change only this voice's profile; retain all checkpoints and evidence."""
    assert_editable(voice_id)
    job = get_job(voice_id)
    if not job:
        raise HTTPException(404, '该音色没有专属训练记录')
    with conn() as c:
        c.execute("UPDATE voices SET model_profile=?,synthesis_status='pending',synthesis_message=? WHERE id=?",
                  (job['previous_profile'], '已恢复训练前权重，正在合成验收', voice_id))
        c.execute("UPDATE voice_adaptations SET status='rolled_back',message=?,updated_at=? WHERE voice_id=?",
                  ('已恢复训练前版本，专属权重和记录仍保留', now(), voice_id))
