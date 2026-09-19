import array
import io
import math
import struct
import wave

import pytest

from app import main, prompt_guard


@pytest.fixture
def anyio_backend():
    return 'asyncio'


def sample(duration=2, amplitude=5000):
    pcm=array.array('h',(int(amplitude*math.sin(2*math.pi*220*i/32000)) for i in range(int(duration*32000))))
    out=io.BytesIO()
    with wave.open(out,'wb') as writer:
        writer.setnchannels(1);writer.setsampwidth(2);writer.setframerate(32000);writer.writeframes(pcm.tobytes())
    return out.getvalue()


@pytest.fixture
def params(tmp_path):
    prompt_guard.CACHE.clear()
    reference=tmp_path/'ref.wav';reference.write_bytes(sample())
    return {'ref_audio_path':str(reference),'aux_ref_audio_paths':[], 'seed':12345,'prompt_text':'参考原文。','text':'今天介绍这款车的配置。'}


@pytest.mark.anyio
async def test_validated_sentence_cached_and_reused_without_more_generation(params):
    calls=[]
    async def generate(p,limit):calls.append(p);return sample()
    audio,meta=await prompt_guard.checked_sentence(params,generate,main._probe_audio_payload,'v2')
    assert audio and len(calls)==1 and meta['prompt_retry_count']==0
    cached,meta=await prompt_guard.checked_sentence(params,generate,main._probe_audio_payload,'v2')
    assert cached==audio and meta['cache_hit'] and len(calls)==1


@pytest.mark.anyio
async def test_silence_retries_seed_without_changing_other_sampling(params):
    calls=[]
    async def generate(p,limit):
        calls.append(p);return sample(amplitude=0) if len(calls)==1 else sample()
    audio,meta=await prompt_guard.checked_sentence(params,generate,main._probe_audio_payload,'v2')
    assert audio and meta['prompt_retry_count']==1 and not meta['fallback_without_prompt']
    assert calls[0]['seed'] != calls[1]['seed']
    assert {k:v for k,v in calls[0].items() if k!='seed'}=={k:v for k,v in calls[1].items() if k!='seed'}


@pytest.mark.anyio
@pytest.mark.parametrize('fallback_good',[True,False])
async def test_no_prompt_fallback_only_after_two_failed_retries(params,fallback_good):
    calls=[]
    async def generate(p,limit):
        calls.append(p)
        if p['prompt_text']:raise prompt_guard.RunawayAudio('duration cap')
        return sample(amplitude=5000 if fallback_good else 0)
    audio,meta=await prompt_guard.checked_sentence(params,generate,main._probe_audio_payload,'v2')
    assert bool(audio)==fallback_good
    assert len(calls)==4 and all(c['prompt_text'] for c in calls[:3]) and calls[-1]['prompt_text']==''
    assert meta['prompt_retry_count']==2 and meta['fallback_without_prompt']
    assert bool(prompt_guard.CACHE)==fallback_good


def test_streaming_placeholder_length_uses_received_frames():
    payload=bytearray(sample())
    struct.pack_into('<I',payload,4,0x7fffffff);struct.pack_into('<I',payload,40,0x7fffffff-36)
    result=main._probe_audio_payload(bytes(payload),expected_text='今天介绍这款车的配置。')
    assert result['duration']==2 and result['status']=='ready'


@pytest.mark.parametrize('declared',[0,0x7fffffff])
def test_model_stream_header_is_rebuilt_from_actual_pcm(declared):
    payload=bytearray(sample())
    struct.pack_into('<I',payload,40,declared)
    fixed=prompt_guard.standard_wav(bytes(payload))
    with wave.open(io.BytesIO(fixed),'rb') as reader:
        assert reader.getnframes()==64000
    assert fixed==sample()


def test_long_internal_silence_is_rejected_even_with_audible_edges(params):
    speech=sample(1)
    with wave.open(io.BytesIO(speech),'rb') as reader:frames=reader.readframes(reader.getnframes())
    out=io.BytesIO()
    with wave.open(out,'wb') as writer:
        writer.setnchannels(1);writer.setsampwidth(2);writer.setframerate(32000)
        writer.writeframes(frames+bytes(32000*2*2)+frames)
    result=prompt_guard.verdict(out.getvalue(),params['text'],main._probe_audio_payload)
    assert not result['ok'] and result['max_internal_silence_s']==2


def test_fused_identity_change_invalidates_checked_audio_cache(params, tmp_path):
    auxiliary = tmp_path/'identity.wav'
    auxiliary.write_bytes(sample())
    p = dict(params, speaker_aux_ref_audio_paths=[str(auxiliary)])
    original = prompt_guard.cache_key(p, 'weights')
    auxiliary.write_bytes(sample(3))
    assert original != prompt_guard.cache_key(p, 'weights')


@pytest.mark.anyio
@pytest.mark.parametrize('cached', [False, True])
@pytest.mark.parametrize('sentences', [['今天介绍这款车。'], ['今天介绍这款车。', '接下来介绍续航。']])
async def test_stream_header_reports_retry_seed_and_supports_existing_players(monkeypatch, cached, sentences):
    import json
    from types import SimpleNamespace

    params = {'top_k': 20, 'top_p': .72, 'temperature': .66, 'seed': 12345,
              'speed_factor': 1, 'streaming_mode': 2, 'prompt_text': '参考文本。'}
    monkeypatch.setattr(main, '_live_unit_params', lambda *args: params.copy())
    monkeypatch.setattr(main, '_voice_model_profile', lambda _: 'base')
    monkeypatch.setattr(main, '_model_profile_weights', lambda _: [])
    monkeypatch.setattr(main, '_voice_config', lambda _: ('ref.wav', '参考文本。', 'zh'))

    async def ready(*args):
        pass

    async def checked(*args):
        return sample(), {'fallback_without_prompt': False, 'prompt_retry_count': 0 if cached else 1,
                          'cache_hit': cached, 'attempts': [{'seed': 12305, 'ok': True}]}

    async def connected():
        return False

    monkeypatch.setattr(main, '_ensure_model_profile_loaded_async', ready)
    monkeypatch.setattr(prompt_guard, 'checked_sentence', checked)
    monkeypatch.setattr(prompt_guard, 'record_status', lambda *args: None)
    response = await main._guarded_prompt_stream(
        main.TTSRequest(text=''.join(sentences), voice_id='clone'),
        SimpleNamespace(is_disconnected=connected), sentences)
    effective = json.loads(response.headers['X-TTS-Effective-Settings'])
    assert effective['seed'] == 12305
    assert effective['cache_hit'] == cached
    stream = b''.join([chunk async for chunk in response.body_iterator])
    # Match the existing GPT streaming wire format: zero-length data header,
    # followed by open-ended PCM. Older players check chunk completeness first.
    assert main._wav_data_offset(stream[:44]) == 44
    assert struct.unpack_from('<I', stream, 4)[0] == 36
    assert struct.unpack_from('<I', stream, 40)[0] == 0
    assert stream[44:] == sample()[44:] * len(sentences)
