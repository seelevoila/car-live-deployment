import asyncio
import io
import json
import math
import wave
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import settings
from app.db import conn, init_db


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'database_path', tmp_path/'audit.db')
    monkeypatch.setattr(settings, 'upload_dir', tmp_path/'uploads')
    init_db()
    return TestClient(main.app)


def test_clear_filters_default_all_and_preserves_non_analytics(client):
    client.post('/api/voice-evaluations', json={'voice_id':'steady','reviewer':'test','text':'测试',
        'similarity':3,'clarity':3,'pause':3,'emotion':3,'overall':3})
    with conn() as c:
        c.execute("INSERT INTO analytics_events(id,kind,created_at) VALUES(?,?,?)",
                  ('old','first_audio',(datetime.now(timezone.utc)-timedelta(days=30)).isoformat()))
        counts = {table:c.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
                  for table in ('voices','documents','chunks','voice_evaluations')}
    for kind in ('first_audio','playback','revision'):
        client.post('/api/analytics/events', json={'id':kind,'kind':kind,'latency_ms':8210,'seconds':2})
    assert client.post('/api/analytics/clear',json={'days':7,'scopes':['first_audio']}).json()['deleted']==1
    with conn() as c:
        assert c.execute("SELECT count(*) FROM analytics_events WHERE id='old'").fetchone()[0]==1
    assert client.post('/api/analytics/clear',json={'scopes':['voices']}).status_code==422
    assert client.post('/api/analytics/clear',json={'scopes':[]}).status_code==422
    assert client.post('/api/analytics/clear',json={}).json()['deleted']==3
    assert client.get('/api/analytics').json()['first_audio']=={'count':0,'average_ms':None,'max_ms':None}
    assert client.post('/api/analytics/clear').json()['deleted']==0
    with conn() as c:
        assert {t:c.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in counts}==counts


def test_calibrated_live_values_and_fixed_seed_survive_sentences(monkeypatch):
    monkeypatch.setattr(main,'_voice_config',lambda _:('ref.wav','参考原文。','zh'))
    monkeypatch.setattr(main,'_voice_aux_reference_paths',lambda _:[])
    monkeypatch.setattr(main,'_voice_sampling_profile',lambda _:{'top_k':10,'top_p':.55,'temperature':.48,'repetition_penalty':1.35,'calibrated':True})
    monkeypatch.setattr(main,'_voice_sampling_seed',lambda _:123456)
    monkeypatch.setattr(settings,'gpt_sovits_live_delivery','natural')
    monkeypatch.setattr(settings,'gpt_sovits_live_seed_mode','fixed')
    a=main._live_unit_params(main.TTSRequest(voice_id='test',text='第一句。'),0)
    b=main._live_unit_params(main.TTSRequest(voice_id='test',text='第二句。'),1)
    assert (a['top_k'],a['top_p'],a['temperature'])==(10,.55,.48)
    assert a['seed']==b['seed']==123456
    monkeypatch.setattr(settings,'gpt_sovits_live_seed_mode','text-low8')
    c=main._live_unit_params(main.TTSRequest(voice_id='test',text='第二句。'),0)
    assert c['seed']>>8==a['seed']>>8


@pytest.mark.parametrize('token',['CLTC','WLTC','150kW','120km/h'])
def test_backend_never_splits_acronyms_or_quantities(token):
    text='前文'+token+'后文'
    for limit in range(3,2+len(token)):
        assert main._safe_tts_cut(text,limit)==2


def test_self_warmup_runs_real_stream_route_with_live_mode_and_no_events(client,monkeypatch):
    import array
    samples=array.array('h',(int(6000*math.sin(i*.1)) for i in range(24000)))
    output=io.BytesIO()
    with wave.open(output,'wb') as f:
        f.setnchannels(1);f.setsampwidth(2);f.setframerate(24000);f.writeframes(samples.tobytes())
    requests=[]
    class PCMStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            data=output.getvalue()
            yield data[:44]
            yield data[44:]
    async def upstream(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200,stream=PCMStream(),headers={'content-type':'audio/wav'})
    async def no_weights(*args): pass
    monkeypatch.setattr(main,'_ensure_tts_ready',lambda:None)
    monkeypatch.setattr(main,'_voice_synthesis_gate',lambda _:None)
    monkeypatch.setattr(main,'_ensure_model_profile_loaded_async',no_weights)
    monkeypatch.setattr(settings,'tts_provider','gpt-sovits')
    monkeypatch.setattr(settings,'gpt_sovits_url','http://model')
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as upstream_client:
            monkeypatch.setattr(main.app.state,'tts_client',upstream_client,raising=False)
            await main._warm_live_path_once()
    try:
        asyncio.run(run())
        assert main.LIVE_PATH_WARMED.is_set()
        assert requests and requests[0]['streaming_mode']==settings.gpt_sovits_live_streaming_mode
        assert requests[0]['parallel_infer'] is False
        assert 'CLTC' in requests[0]['text'] and 'EV' in requests[0]['text']
        assert client.get('/api/analytics').json()['first_audio']['count']==0
    finally:
        main.LIVE_PATH_WARMED.clear()
        main.VOICE_WARMED.discard('steady')


def test_ready_waits_for_actual_live_path(client,monkeypatch):
    monkeypatch.setattr(settings,'tts_provider','gpt-sovits')
    monkeypatch.setattr(main,'_tts_has_reference',lambda:True)
    monkeypatch.setattr(main,'_gpt_sovits_reachable',lambda:True)
    main.LIVE_PATH_WARMED.clear()
    assert client.get('/api/tts/status').json()['ready'] is False
    main.LIVE_PATH_WARMED.set()
    try:
        result=client.get('/api/tts/status').json()
        assert result['ready'] and result['live_path_warmed']
    finally:
        main.LIVE_PATH_WARMED.clear()
