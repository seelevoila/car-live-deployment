"""Launch the existing API with tested stream boundaries and reference caching."""
import argparse
import os
from pathlib import Path
import runpy
import sys
import re
from typing import Optional, List
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--gpt-root', type=Path, required=True)
    parser.add_argument('--audit-log', type=Path, help='Optional per-request semantic/acoustic chunk measurements')
    project = Path(__file__).resolve().parents[1]
    parser.add_argument('--voice-model-root', type=Path, default=project / 'data/voice_models')
    parser.add_argument('--voice-upload-root', type=Path, default=project / 'data/uploads/voices')
    args, upstream_args = parser.parse_known_args()
    root = args.gpt_root.resolve()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / 'GPT_SoVITS'))
    os.chdir(root)
    sys.argv = [str(root / 'api_v2.py'), *upstream_args]
    import torch
    torch.set_num_threads(4)
    from app.gpt_sovits_runtime import install
    install()
    api = runpy.run_path(str(root / 'api_v2.py'), run_name='car_live_gpt_api')
    pipeline = api['tts_pipeline']
    if args.audit_log:
        from app.tts_audit import instrument_pipeline
        instrument_pipeline(pipeline, args.audit_log.resolve())
    instance_id = uuid4().hex
    from app.runtime_serialization import ModelLeaseMiddleware
    from app.short_adaptation import adapt_resident
    from fastapi import HTTPException
    api['APP'].add_middleware(ModelLeaseMiddleware)
    adaptation_state = {'running': False}
    model_root, upload_root = args.voice_model_root.resolve(), args.voice_upload_root.resolve()

    # Some local distributions ship a status stub with stale/empty weight
    # paths. Starlette resolves the first matching route, so replace it before
    # registering the runtime's authoritative status and preparation endpoints.
    api['APP'].router.routes[:] = [
        route for route in api['APP'].router.routes
        if getattr(route, 'path', None) not in {'/runtime/status', '/runtime/prime'}
        and not (getattr(route, 'path', None) == '/tts' and 'POST' in getattr(route, 'methods', set()))
    ]

    class LiveTTSRequest(api['TTS_Request']):
        speaker_ref_audio_path: Optional[str] = None
        speaker_aux_ref_audio_paths: Optional[List[str]] = None
        speaker_similarity_threshold: float = .85

    @api['APP'].post('/tts')
    async def live_tts(request: LiveTTSRequest):
        return await api['tts_handle'](request.dict())

    @api['APP'].get('/runtime/status')
    def runtime_status():
        return {
            'runtime': 'car-live-gpt-sovits', 'revision': 2,
            'instance_id': instance_id,
            'gpt_weights': str(Path(pipeline.configs.t2s_weights_path).resolve()),
            'sovits_weights': str(Path(pipeline.configs.vits_weights_path).resolve()),
            'reference_cache_size': len(getattr(pipeline, '_voice_cache', {})),
            'reference_cache_hits': getattr(pipeline, '_voice_cache_hits', 0),
            'device': str(pipeline.configs.device),
            'adaptation': dict(adaptation_state),
            'adaptation_supported': True,
        }

    @api['APP'].post('/runtime/adapt')
    def adapt_voice(request: dict):
        job_id = request.get('job_id', '')
        records = request.get('records', [])
        if not re.fullmatch(r'[a-f0-9]{32}', job_id) or not isinstance(records, list) or not 1 <= len(records) <= 3:
            raise HTTPException(422, 'Invalid adaptation job')
        for record in records:
            source = Path(record.get('audio', '')).resolve()
            if (upload_root not in source.parents or not source.is_file()
                    or not isinstance(record.get('transcript'), str) or not 4 <= len(record['transcript'].strip()) <= 500
                    or record.get('language', 'zh') not in {'zh', 'en', 'ja', 'ko', 'yue'}):
                raise HTTPException(422, 'Invalid adaptation recording or transcript')
            record['audio'] = str(source)
        seconds, steps = request.get('seconds', 30.), request.get('max_steps', 24)
        if not isinstance(seconds, (float, int)) or not 10 <= seconds <= 60 or not isinstance(steps, int) or not 1 <= steps <= 32:
            raise HTTPException(422, 'Invalid adaptation budget')
        adaptation_state.update(running=True, job_id=job_id, stage='starting', steps=0)
        try:
            return adapt_resident(pipeline, root, records, model_root / 'adaptations' / job_id,
                                  seconds=seconds, max_steps=steps, progress=adaptation_state.update)
        except Exception as exc:
            raise HTTPException(500, str(exc)[:500]) from exc
        finally:
            adaptation_state['running'] = False

    @api['APP'].post('/runtime/prime')
    def prime_reference(request: dict):
        for _ in pipeline.run({**request, '_prepare_reference_only': True}):
            pass
        return {'ready': True}

    api['uvicorn'].run(api['APP'], host=api['host'], port=api['port'], workers=1)


if __name__ == '__main__':
    main()
