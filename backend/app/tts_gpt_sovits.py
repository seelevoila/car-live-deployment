"""GPT-SoVITS transport helpers.

The application keeps GPT-SoVITS-specific HTTP details in this module so the
Sampling and voice profile construction remain in the application because
those values are persisted in the existing voice library.
"""

from __future__ import annotations

from pathlib import Path
import json
import re

import httpx


def model_profiles(settings):
    """Local, explicitly installed profiles; never accept checkpoint paths from clients."""
    profiles = {
        'base': {'gpt_weights': settings.gpt_sovits_base_gpt_weights,
                 'sovits_weights': settings.gpt_sovits_base_sovits_weights},
    }
    manifest = Path(settings.gpt_sovits_profiles_file)
    custom = {}
    if manifest.is_file():
        custom.update(json.loads(manifest.read_text(encoding='utf-8')))
    for installed in sorted((manifest.parent / 'adaptations').glob('*/profile.json')):
        entries = json.loads(installed.read_text(encoding='utf-8'))
        if set(entries) & set(custom):
            raise RuntimeError('Duplicate installed GPT-SoVITS profile')
        custom.update(entries)
    if custom:
        for name, profile in custom.items():
            if name in profiles or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,79}', name):
                raise RuntimeError('Invalid custom GPT-SoVITS profile name')
            entry = {}
            for key in ('gpt_weights', 'sovits_weights', 'speaker_ref_audio_path'):
                path = profile.get(key)
                if not path:
                    if key != 'speaker_ref_audio_path':
                        raise RuntimeError(f'Missing {key} for profile {name}')
                    continue
                value = Path(path)
                entry[key] = str((value if value.is_absolute() else manifest.parent / value).resolve())
            if 'speaker_aux_ref_audio_paths' in profile:
                paths = profile['speaker_aux_ref_audio_paths']
                if not isinstance(paths, list) or any(not isinstance(p, str) or not p for p in paths):
                    raise RuntimeError(f'Invalid speaker auxiliary paths for profile {name}')
                if not entry.get('speaker_ref_audio_path'):
                    raise RuntimeError(f'Speaker auxiliaries require a primary anchor for profile {name}')
                entry['speaker_aux_ref_audio_paths'] = [str((Path(p) if Path(p).is_absolute() else manifest.parent / p).resolve()) for p in paths]
            profiles[name] = entry
    return profiles


def profile_weights(settings, profile):
    entry = model_profiles(settings).get(profile)
    if entry is None:
        raise RuntimeError(f'Unknown GPT-SoVITS profile: {profile}')
    return entry['gpt_weights'], entry['sovits_weights']


def _same_weights(status, gpt_weights, sovits_weights):
    return (status.get('runtime') == 'car-live-gpt-sovits'
            and Path(status.get('gpt_weights', '')).resolve() == Path(gpt_weights).resolve()
            and Path(status.get('sovits_weights', '')).resolve() == Path(sovits_weights).resolve())


def delivery_text(text: str, style: str, speed: float):
    """Small punctuation/pace cues; keep the speaker seed and factual text intact."""
    if style == 'lively' and re.search(r'欢迎|大家好|一起了解',text) and text.endswith('。'):
        text=text[:-1]+'！'
    if style in {'warm','lively'}:
        if re.search(r'公里|千瓦|毫米|万元|百分|补贴|质保',text):
            speed*=0.97  # give figures time to land
        elif text.endswith(('？','?')):
            speed*=0.985
    return text,max(0.6,min(1.6,speed))


class GptSovitsEngine:
    provider = "gpt-sovits"
    label = "GPT-SoVITS"

    @staticmethod
    def configured(settings) -> bool:
        return bool(settings.gpt_sovits_url)

    @staticmethod
    def endpoint(settings) -> str:
        if not settings.gpt_sovits_url:
            raise RuntimeError("GPT-SoVITS 未配置")
        base = settings.gpt_sovits_url.rstrip("/")
        return base if base.endswith("/tts") else base + "/tts"

    @staticmethod
    def probe(settings) -> bool:
        if not GptSovitsEngine.configured(settings):
            return False
        base = settings.gpt_sovits_url.rstrip("/")
        if base.endswith("/tts"):
            base = base[:-4]
        try:
            with httpx.Client(timeout=1.5, trust_env=False) as client:
                return client.get(base + "/docs").is_success
        except httpx.HTTPError:
            return False

    @staticmethod
    def load_weights(settings, profile: str, client: httpx.Client) -> None:
        if not GptSovitsEngine.configured(settings):
            raise RuntimeError("GPT-SoVITS 未配置")
        gpt_weights, sovits_weights = profile_weights(settings, profile)
        if not (Path(gpt_weights).is_file() and Path(sovits_weights).is_file()):
            raise RuntimeError(f"{profile} 音色模型权重不存在，请检查 GPT-SoVITS 配置")
        base = settings.gpt_sovits_url.rstrip("/")
        try:
            status = client.get(base + '/runtime/status', timeout=2)
            if status.is_success and _same_weights(status.json(), gpt_weights, sovits_weights):
                return
        except (httpx.HTTPError, ValueError):
            pass
        for route, weights in (("/set_gpt_weights", gpt_weights), ("/set_sovits_weights", sovits_weights)):
            response = client.get(base + route, params={"weights_path": weights}, timeout=180)
            response.raise_for_status()

    @staticmethod
    async def load_weights_async(settings, profile: str, client: httpx.AsyncClient) -> None:
        if not GptSovitsEngine.configured(settings):
            raise RuntimeError("GPT-SoVITS 未配置")
        gpt_weights, sovits_weights = profile_weights(settings, profile)
        if not (Path(gpt_weights).is_file() and Path(sovits_weights).is_file()):
            raise RuntimeError(f"{profile} 音色模型权重不存在，请检查 GPT-SoVITS 配置")
        base = settings.gpt_sovits_url.rstrip("/")
        try:
            status = await client.get(base + '/runtime/status', timeout=2)
            if status.is_success and _same_weights(status.json(), gpt_weights, sovits_weights):
                return
        except (httpx.HTTPError, ValueError):
            pass
        for route, weights in (("/set_gpt_weights", gpt_weights), ("/set_sovits_weights", sovits_weights)):
            response = await client.get(base + route, params={"weights_path": weights}, timeout=180)
            response.raise_for_status()

    @staticmethod
    def synthesize(settings, client: httpx.Client, params: dict) -> httpx.Response:
        response = client.post(GptSovitsEngine.endpoint(settings), json=params)
        response.raise_for_status()
        return response


gpt_sovits_engine = GptSovitsEngine()
