import array
import io
import math
import wave

import pytest

from app.audio_metrics import compress_internal_pauses, wav_metrics


def wav(parts, rate=24000):
    samples=array.array('h')
    for duration, amplitude in parts:
        samples.extend(round(amplitude*math.sin(2*math.pi*220*i/rate)) for i in range(round(duration*rate)))
    out=io.BytesIO()
    with wave.open(out,'wb') as writer:
        writer.setnchannels(1);writer.setsampwidth(2);writer.setframerate(rate);writer.writeframes(samples.tobytes())
    return out.getvalue()


def test_pause_compression_retains_edges_and_speech(tmp_path):
    payload=wav([(.5,0),(1,9000),(1.08,0),(1,9000),(.6,0)])
    source=tmp_path/'original.wav';source.write_bytes(payload)
    target=tmp_path/'compressed.wav'
    result=compress_internal_pauses(source,target)
    assert source.read_bytes()==payload
    assert result['before']['max_internal_silence_s']==1.08
    assert result['after']['max_internal_silence_s']==.34
    assert result['after']['duration_s']==pytest.approx(3.44)
    with wave.open(str(target),'rb') as reader:
        pcm=reader.readframes(reader.getnframes())
    assert pcm[:24000]==bytes(24000)
    assert pcm[-28800:]==bytes(28800)


def test_negative_int16_extreme_is_valid_pcm():
    payload=io.BytesIO()
    with wave.open(payload,'wb') as writer:
        writer.setnchannels(1);writer.setsampwidth(2);writer.setframerate(24000)
        writer.writeframes(array.array('h',[-32768]*24000).tobytes())
    assert wav_metrics(payload.getvalue())['peak_db']==0
