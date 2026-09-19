"""Validate complete sentences before releasing prompt-conditioned audio."""
from collections import OrderedDict
import hashlib
import io
import json
from pathlib import Path
import re
import struct
import wave

from .audio_metrics import wav_metrics

CACHE = OrderedDict()
STATUS = OrderedDict()
MAX_CACHE_BYTES = 24 * 1024 * 1024


class RunawayAudio(RuntimeError):
    pass


def duration_limit(text):
    symbols = len(re.sub(r'[\W_]+', '', text, flags=re.UNICODE))
    return max(2.5, max(.6, symbols / 4.5) * 2)


def standard_wav(payload):
    """Replace an unbounded streaming header with the actual frame length."""
    with wave.open(io.BytesIO(payload), 'rb') as reader:
        params = reader.getparams()
    offset=12
    while offset+8<=len(payload):
        size=struct.unpack_from('<I',payload,offset+4)[0]
        if payload[offset:offset+4]==b'data':
            frames=payload[offset+8:];break
        offset+=8+size+(size%2)
    else:
        raise ValueError('Missing PCM data chunk')
    if len(frames) % (params.sampwidth*params.nchannels):
        raise ValueError('Incomplete PCM frame')
    output = io.BytesIO()
    with wave.open(output, 'wb') as writer:
        writer.setparams(params);writer.writeframes(frames)
    return output.getvalue()


def verdict(payload, text, probe):
    check = probe(payload, expected_text=text)
    metrics = wav_metrics(payload)
    reasons = [] if check['status'] == 'ready' else [check['message']]
    if metrics['max_internal_silence_s'] > 1.5:
        reasons.append('句中静音超过 1.5 秒')
    return {'ok':not reasons,'reasons':reasons,**metrics}


def cache_key(params, model_identity):
    stamps=[]
    for path in [params['ref_audio_path'],*params.get('aux_ref_audio_paths',[]),
                 *([params['speaker_ref_audio_path']] if params.get('speaker_ref_audio_path') else []),
                 *(params.get('speaker_aux_ref_audio_paths') or [])]:
        stat=Path(path).stat();stamps.append((path,stat.st_size,stat.st_mtime_ns))
    return hashlib.sha256(json.dumps([params,model_identity,stamps],sort_keys=True,ensure_ascii=False).encode()).hexdigest()


async def checked_sentence(params, generate, probe, model_identity):
    key=cache_key(params,model_identity)
    if key in CACHE:
        payload, original=CACHE.pop(key);CACHE[key]=(payload,original)
        return payload,{**original,'prompt_retry_count':0,'cache_hit':True,
                        'cached_original_retry_count':original['prompt_retry_count']}
    seed=params['seed'];seeds=[seed]
    for low in (42,17,73):
        candidate=(seed & ~255)|low
        if candidate not in seeds:seeds.append(candidate)
    attempts=[];selected=None;fallback=False
    for index, candidate in enumerate(seeds[:3]):
        attempt={**params,'seed':candidate}
        try:
            payload=standard_wav(await generate(attempt,duration_limit(params['text'])))
            check=verdict(payload,params['text'],probe)
        except (RunawayAudio, ValueError, wave.Error, EOFError) as exc:
            check={'ok':False,'reasons':[str(exc)]}
        attempts.append({'seed':candidate,'use_prompt_text':True,**check})
        if check['ok']:
            selected=payload;break
    if selected is None:
        fallback=True
        attempt={**params,'prompt_text':''}
        try:
            payload=standard_wav(await generate(attempt,duration_limit(params['text'])))
            check=verdict(payload,params['text'],probe)
        except (RunawayAudio, ValueError, wave.Error, EOFError) as exc:
            check={'ok':False,'reasons':[str(exc)]}
        attempts.append({'seed':seed,'use_prompt_text':False,**check})
        if check['ok']:selected=payload
    metadata={'prompt_retry_count':min(2,sum(a['use_prompt_text'] for a in attempts)-1),
              'fallback_without_prompt':fallback,'cache_hit':False,'attempts':attempts,
              'text':params['text'],'ok':selected is not None}
    if selected is not None:
        CACHE[key]=(selected,metadata)
        while sum(len(item[0]) for item in CACHE.values()) > MAX_CACHE_BYTES or len(CACHE)>64:
            CACHE.popitem(last=False)
    return selected,metadata


def record_status(voice_id, request_id, checks):
    STATUS.pop(voice_id,None)
    STATUS[voice_id]={'request_id':request_id,'prompt_retry_count':sum(c['prompt_retry_count'] for c in checks),
                      'fallback_count':sum(c['fallback_without_prompt'] for c in checks),'checks':list(checks)}
    while len(STATUS)>24:STATUS.popitem(last=False)
