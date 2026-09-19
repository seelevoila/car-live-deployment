import json
from pathlib import Path

import httpx
import pytest
from dotenv import dotenv_values
from fastapi.testclient import TestClient

from app import main, llm_gateway, llm_settings
from app.config import Settings, settings


@pytest.fixture
def configured(tmp_path, monkeypatch):
    path = tmp_path / '.env'
    path.write_bytes(b"# keep this comment\r\nTTS_PROVIDER=gpt-sovits\r\nLIVE2D_MODEL_ROOT='C:/models/avatar'\r\nLLM_BASE_URL='https://model.example/v1'\r\nLLM_MODEL='old-model'\r\nLLM_API_KEY='test-old-secret'\r\nLLM_TIMEOUT_SECONDS=12\r\n")
    monkeypatch.setattr(llm_settings, 'ENV_PATH', path)
    for name, value in {'llm_base_url':'https://model.example/v1', 'llm_model':'old-model',
                        'llm_api_key':'test-old-secret', 'llm_timeout_seconds':12.0}.items():
        monkeypatch.setattr(settings, name, value)
    return TestClient(main.app), path


def body(**changes):
    return {'base_url':'https://model.example/v1', 'model':'new-model', 'timeout_seconds':20, **changes}


def test_save_applies_to_next_inference_preserves_key_and_survives_restart(configured, monkeypatch):
    client, path = configured
    response = client.put('/api/llm/config', json=body(api_key=''))
    assert response.status_code == 200
    assert response.json()['model'] == 'new-model'
    assert 'test-old-secret' not in response.text
    config = client.get('/api/llm/config').json()
    assert config['api_key_configured'] is True and 'api_key' not in config
    assert config['status']['configured'] is True
    assert path.read_bytes().startswith(b'# keep this comment\r\nTTS_PROVIDER=gpt-sovits\r\n')
    loaded = Settings(_env_file=path)
    assert loaded.llm_model == 'new-model' and loaded.llm_api_key == 'test-old-secret'
    assert loaded.llm_timeout_seconds == 20
    assert loaded.live2d_model_root == 'C:/models/avatar'
    calls = []
    def post(_client, url, **kwargs):
        calls.append((url, kwargs))
        return httpx.Response(200, request=httpx.Request('POST', url), json={'choices':[{'message':{'content':'续航580公里。[1]'}}]})
    monkeypatch.setattr(httpx.Client, 'post', post)
    assert llm_gateway.generate('续航是多少', [{'content':'续航580公里'}])
    assert calls[0][0] == 'https://model.example/v1/chat/completions'
    assert calls[0][1]['json']['model'] == 'new-model'
    assert calls[0][1]['headers']['Authorization'] == 'Bearer test-old-secret'


def test_replace_and_clear_secret_without_echoing_it(configured):
    client, path = configured
    secret = "test-new-'quoted'\\secret#"
    saved = client.put('/api/llm/config', json=body(api_key=secret))
    assert saved.status_code == 200
    assert dotenv_values(path)['LLM_API_KEY'] == secret
    assert secret not in saved.text and secret not in client.get('/api/llm/config').text
    cleared = client.put('/api/llm/config', json=body(clear_api_key=True))
    assert cleared.status_code == 200 and cleared.json()['api_key_configured'] is False
    assert dotenv_values(path)['LLM_API_KEY'] == '' and settings.llm_api_key == ''


@pytest.mark.parametrize('changes', [
    {'base_url':'file:///tmp/private'}, {'base_url':'https://secret@model.example/v1'},
    {'base_url':'https://model.example/v1?api_key=secret'}, {'model':'bad\nMODEL=other'},
    {'timeout_seconds':0}, {'timeout_seconds':121}, {'api_key':'secret\nEXTRA=bad'},
    {'api_key':'test-key', 'clear_api_key':True}, {'api_key':{'secret':'test-key'}},
])
def test_invalid_fields_do_not_write_or_echo_secrets(configured, changes):
    client, path = configured
    before = path.read_bytes()
    response = client.put('/api/llm/config', json=body(**changes))
    assert response.status_code == 422
    assert 'test-key' not in response.text and 'test-old-secret' not in response.text
    assert path.read_bytes() == before and settings.llm_model == 'old-model'


def test_file_failure_keeps_previous_runtime_and_disk_settings(configured, monkeypatch):
    client, path = configured
    before = path.read_bytes()
    def fail(*args): raise PermissionError('test file locked')
    monkeypatch.setattr(llm_settings.os, 'replace', fail)
    response = client.put('/api/llm/config', json=body(api_key='test-new-secret'))
    assert response.status_code == 503
    assert settings.llm_model == 'old-model' and settings.llm_api_key == 'test-old-secret'
    assert path.read_bytes() == before and not list(path.parent.glob('.llm-*.tmp'))


def test_changed_service_needs_its_own_key_and_foreign_pages_cannot_save(configured):
    client, path = configured
    before = path.read_bytes()
    response = client.put('/api/llm/config', json=body(base_url='https://different.example/v1'))
    assert response.status_code == 422 and path.read_bytes() == before
    foreign = client.put('/api/llm/config', json=body(), headers={'Origin':'https://unrelated.example'})
    assert foreign.status_code == 403 and path.read_bytes() == before
    good = client.put('/api/llm/config', json=body(base_url='http://localhost:9000/v1',clear_api_key=True))
    assert good.status_code == 200 and not good.json()['api_key_configured']


def test_duplicate_env_entries_are_replaced_together_and_other_values_are_untouched(configured):
    client, path = configured
    with path.open('a', encoding='utf-8') as out:
        out.write("LLM_MODEL='another-model'\nUNRELATED='two\nlines'\n")
    response = client.put('/api/llm/config', json=body())
    assert response.status_code == 200
    assert path.read_text().count('LLM_MODEL=') == 1
    assert dotenv_values(path)['UNRELATED'] == 'two\nlines'


def test_inflight_inference_uses_one_configuration_snapshot(configured, monkeypatch):
    _, path = configured
    original_endpoint = llm_gateway.endpoint
    def change_after_snapshot(config=None):
        # Simulate a save between capturing a request and creating its HTTP call.
        llm_settings.save_configuration(llm_settings.ModelConfiguration(**body(api_key='test-new-secret')))
        return original_endpoint(config)
    monkeypatch.setattr(llm_gateway, 'endpoint', change_after_snapshot)
    calls = []
    def post(_client, url, **kwargs):
        calls.append(kwargs)
        return httpx.Response(200, request=httpx.Request('POST', url), json={'choices':[{'message':{'content':'续航580公里'}}]})
    monkeypatch.setattr(httpx.Client, 'post', post)
    # Avoid recursively changing configuration while the save reports status.
    monkeypatch.setattr(llm_gateway, 'status', lambda: {'configured':True})
    assert llm_gateway.generate('续航', [{'content':'续航580公里'}])
    assert calls[0]['json']['model'] == 'old-model'
    assert calls[0]['headers']['Authorization'] == 'Bearer test-old-secret'
    assert settings.llm_model == 'new-model'
