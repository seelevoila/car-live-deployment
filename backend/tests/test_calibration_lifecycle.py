import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import main, runtime_paths
from app.config import settings
from app.db import conn, init_db


@pytest.mark.parametrize('interpreter', ['runtime/python.exe', '.venv/Scripts/python.exe', '.venv/bin/python'])
def test_speaker_root_uses_source_for_runtime_and_venv(tmp_path, monkeypatch, interpreter):
    root = tmp_path / 'GPT-SoVITS'
    source = root / 'GPT_SoVITS/eres2net/ERes2NetV2.py'
    source.parent.mkdir(parents=True); source.touch()
    monkeypatch.setattr(runtime_paths, 'detect_gpt_sovits_root', lambda: None)
    assert runtime_paths.speaker_model_root(root / interpreter, root / 'checkpoint.pth') == root


@pytest.fixture
def calibration_voice(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'database_path', tmp_path / 'db.sqlite')
    monkeypatch.setattr(settings, 'upload_dir', tmp_path / 'uploads')
    monkeypatch.setattr(settings, 'gpt_sovits_calibration_enabled', True)
    init_db()
    with conn() as c:
        c.execute("INSERT INTO voices(id,reference_path,prompt_text,model_profile,synthesis_status) VALUES(?,?,?,?,?)",
                  ('clone', str(tmp_path / 'ref.wav'), '参考文本。', 'base', 'ready'))
    return 'clone'


def test_scorer_failure_persists_reason_and_keeps_unscreened_null(calibration_voice, tmp_path, monkeypatch):
    python = tmp_path / 'python.exe'; python.touch()
    checkpoint = tmp_path / 'speaker.ckpt'; checkpoint.touch()
    monkeypatch.setattr(settings, 'gpt_sovits_python', str(python))
    monkeypatch.setattr(settings, 'gpt_sovits_speaker_model', str(checkpoint))
    monkeypatch.setattr(main, 'speaker_model_root', lambda *args: tmp_path)
    monkeypatch.setattr(main.subprocess, 'run', lambda *a, **kw: SimpleNamespace(
        returncode=1, stdout='', stderr="ModuleNotFoundError: No module named 'ERes2NetV2'"))
    assert main._calibrate_voice(calibration_voice) is None
    with conn() as c:
        row = c.execute('SELECT * FROM voices WHERE id=?', (calibration_voice,)).fetchone()
    assert row['calibration_status'] == 'failed'
    assert 'ERes2NetV2' in row['calibration_message']
    assert row['sampling_seed'] is None
    assert row['validated_aux_reference_paths'] is None
    evidence = list((settings.upload_dir / 'voice-calibration').glob('*/references.json'))
    assert json.loads(evidence[0].read_text(encoding='utf-8'))['returncode'] == 1


def test_startup_schedules_only_incomplete_clones(calibration_voice, monkeypatch):
    queued = []
    monkeypatch.setattr(main, '_schedule_voice_calibration', queued.append)
    main._schedule_incomplete_calibrations()
    assert queued == ['clone']
    main._save_voice_calibration('clone', 42, [], top_k=15)
    queued.clear()
    main._schedule_incomplete_calibrations()
    assert queued == []


def test_manual_calibration_preserves_previous_profile_until_success(calibration_voice, monkeypatch):
    main._save_voice_calibration('clone', 42, [], top_k=15)
    calls = []
    monkeypatch.setattr(main, '_tts_provider', lambda: 'gpt-sovits')
    monkeypatch.setattr(main, '_schedule_voice_calibration', lambda voice, **kw: calls.append((voice, kw)))
    assert main.calibrate_voice('clone')['status'] == 'queued'
    assert calls == [('clone', {'force': True})]
    with conn() as c:
        row = c.execute('SELECT sampling_seed,validated_aux_reference_paths FROM voices WHERE id=?', ('clone',)).fetchone()
    assert tuple(row) == (42, '[]')
