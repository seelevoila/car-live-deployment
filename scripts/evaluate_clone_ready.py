"""Exercise clone upload -> accepted -> stream; remove only the created fixture."""
import argparse
import json
from pathlib import Path
import sqlite3
import time

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--voice', default='voice-a58847fe6169')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    with sqlite3.connect(root / 'data/car_live.db') as db:
        reference, prompt = db.execute('SELECT reference_path,prompt_text FROM voices WHERE id=?', (args.voice,)).fetchone()
    voice_id = None
    report = {'source_voice': args.voice}
    with httpx.Client(base_url='http://127.0.0.1:8000', timeout=120, trust_env=False) as client:
        try:
            start = time.perf_counter()
            with open(reference, 'rb') as sample:
                response = client.post('/api/voices/clone', files={'sample': ('sample.wav', sample, 'audio/wav')},
                                       data={'name': 'TTS regression fixture', 'prompt_text': prompt})
            response.raise_for_status()
            voice_id = response.json()['id']
            report['upload_ms'] = round((time.perf_counter() - start) * 1000, 1)
            deadline = time.perf_counter() + 120
            while time.perf_counter() < deadline:
                voices = client.get('/api/voices').json()
                voice = next(voice for voice in voices if voice['id'] == voice_id)
                if voice['synthesis_check']['status'] == 'failed':
                    raise RuntimeError(voice['synthesis_check']['message'])
                if voice['warmed'] and not voice['warming']:
                    report.update(ready_ms=round((time.perf_counter()-start)*1000, 1),
                                  calibration_pending=voice['calibration_pending'], calibrating=voice['calibrating'])
                    break
                time.sleep(.25)
            else:
                raise TimeoutError('Clone did not become ready')
            response = client.post('/api/tts/stream', json={'voice_id': voice_id, 'text': '今天介绍这款车的续航和智能配置。'})
            response.raise_for_status()
            report['stream_bytes'] = len(response.content)
            report['ok'] = len(response.content) > 10000
        finally:
            if voice_id:
                client.delete(f'/api/voices/{voice_id}').raise_for_status()
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
            print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
