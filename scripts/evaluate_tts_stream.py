"""Measure real PCM arrival and retain audio for offline content evaluation."""
import argparse
import json
import math
import struct
import time
import wave
from pathlib import Path

import httpx


TEXTS = [
    "今天介绍这款车的续航和智能配置。",
    "从30%充到80%需要0.33小时[2]，纯电续航为580公里。",
    "激光雷达可以辅助感知周围环境，驾驶员仍需时刻关注路况。",
    "你平时主要在市区通勤，还是经常跑高速？",
    "接下来看看车内空间，轴距为2720毫米。",
    "最大功率150千瓦，具体优惠以门店最新报价为准。",
]


def wav_offset(data):
    if len(data) < 12:
        return None
    if data[:4] != b'RIFF' or data[8:12] != b'WAVE':
        raise ValueError('not a WAV response')
    offset = 12
    while offset + 8 <= len(data):
        size = struct.unpack_from('<I', data, offset + 4)[0]
        if data[offset:offset + 4] == b'data':
            return offset + 8
        offset += 8 + size + size % 2
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--voices', nargs='+', default=['steady', 'voice-a58847fe6169', 'voice-46458822000f', 'voice-ff9f6ad7787d'])
    parser.add_argument('--count', type=int, default=6)
    parser.add_argument('--prime', action='store_true', help='Match selection-time reference priming in the browser')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    results = []
    with httpx.Client(base_url='http://127.0.0.1:8000', timeout=120, trust_env=False) as client:
        for voice in args.voices:
            prime_ms = None
            if args.prime:
                prime_started = time.perf_counter()
                prepared = client.post(f'/api/voices/{voice}/prime')
                prepared.raise_for_status()
                if not prepared.json().get('ready'):
                    raise RuntimeError(f'Voice preparation failed: {voice}')
                prime_ms = round((time.perf_counter() - prime_started) * 1000, 1)
            for index, text in enumerate(TEXTS[:args.count]):
                record = {'voice': voice, 'text': text, 'selection_prime_ms': prime_ms}
                started = time.perf_counter()
                data = bytearray()
                first_pcm = None
                try:
                    with client.stream('POST', '/api/tts/stream', json={
                        'voice_id': voice, 'text': text, 'unitized': True, 'stream_batch': True,
                    }) as response:
                        response.raise_for_status()
                        for chunk in response.iter_bytes():
                            data.extend(chunk)
                            offset = wav_offset(data)
                            if first_pcm is None and offset is not None and len(data) > offset:
                                first_pcm = round((time.perf_counter() - started) * 1000, 1)
                    offset = wav_offset(data)
                    if offset is None or len(data) <= offset:
                        raise ValueError('empty PCM stream')
                    rate = struct.unpack_from('<I', data, 24)[0]
                    channels = struct.unpack_from('<H', data, 22)[0]
                    width = struct.unpack_from('<H', data, 34)[0] // 8
                    audio_path = args.output / f'{voice}-{index:02}.wav'
                    with wave.open(str(audio_path), 'wb') as output:
                        output.setnchannels(channels)
                        output.setsampwidth(width)
                        output.setframerate(rate)
                        output.writeframes(data[offset:])
                    record.update(first_pcm_ms=first_pcm, total_ms=round((time.perf_counter()-started)*1000, 1),
                                  duration=round((len(data)-offset)/rate/channels/width, 3),
                                  wav_headers=data.count(b'RIFF'), audio=str(audio_path.resolve()), ok=True)
                except Exception as error:
                    record.update(ok=False, error=str(error))
                results.append(record)
                print(json.dumps(record, ensure_ascii=True), flush=True)
                (args.output / 'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    values = sorted(item['first_pcm_ms'] for item in results if item['ok'])
    print(json.dumps({'samples': len(results), 'success': len(values),
                      'p95_pcm_ms': values[math.ceil(len(values)*.95)-1] if values else None}), flush=True)


if __name__ == '__main__':
    main()
