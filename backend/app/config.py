from pathlib import Path
from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict
from .runtime_paths import (
    detect_gpt_sovits_root,
    detect_gpt_sovits_python,
    detect_live2d_model_root,
)

ROOT = Path(__file__).resolve().parents[2]

# Detect external dependencies at import time
_GPT_SOVITS_ROOT = detect_gpt_sovits_root()
_GPT_SOVITS_PYTHON = detect_gpt_sovits_python()
_LIVE2D_ROOT = detect_live2d_model_root()

class Settings(BaseSettings):
    database_path: Path = ROOT / "data" / "car_live.db"
    upload_dir: Path = ROOT / "data" / "uploads"
    sample_dir: Path = ROOT / "data" / "sample"
    testset_path: Path = ROOT / "data" / "testset" / "retrieval_questions.json"
    llm_provider: str = "local"
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_timeout_seconds: float = 12
    rag_model_dir: Path = ROOT / 'models' / 'rag'
    rag_threads: int = 2
    rag_rerank_candidates: int = 12
    # Optional separate ONNX encoder export with the same CLS pooling contract.
    # Changing model files requires rebuilding the index; manifest hashes identify it.
    rag_embedding_query_prefix: str = '为这个句子生成表示以用于检索相关文章：'
    # The server-side speech engine is GPT-SoVITS v2ProPlus.
    tts_provider: str = "gpt-sovits"
    gpt_sovits_url: str = ""
    gpt_sovits_ref_audio: str = ""
    gpt_sovits_prompt_text: str = ""
    gpt_sovits_prompt_language: str = "zh"
    gpt_sovits_text_language: str = "zh"
    gpt_sovits_model_version: str = "v2ProPlus"
    # Optional post-clone speaker-embedding calibration.  It runs in the
    # GPT-SoVITS environment and falls back to deterministic inference when
    # that environment or its speaker encoder is unavailable.
    gpt_sovits_calibration_enabled: bool = True
    gpt_sovits_calibration_idle_seconds: float = 15.0
    # Per-new-voice acoustic adaptation. This is a soft resident training
    # budget; upload, queueing and checked synthesis acceptance are additional.
    gpt_sovits_adaptation_enabled: bool = True
    gpt_sovits_adaptation_seconds: float = 30.0
    gpt_sovits_adaptation_max_steps: int = 24
    gpt_sovits_python: str = str(_GPT_SOVITS_PYTHON) if _GPT_SOVITS_PYTHON else ""
    gpt_sovits_speaker_model: str = (
        str(_GPT_SOVITS_ROOT / "GPT_SoVITS" / "pretrained_models" / "sv" / "pretrained_eres2netv2w24s4ep4.ckpt")
        if _GPT_SOVITS_ROOT else ""
    )
    gpt_sovits_aux_similarity_threshold: float = 0.85
    # The API process holds one GPT-SoVITS model at a time. Keep the official
    # v2ProPlus pair available for new clones and installed custom profiles
    # separate from it.
    gpt_sovits_base_gpt_weights: str = (
        str(_GPT_SOVITS_ROOT / "GPT_SoVITS" / "pretrained_models" / "s1v3.ckpt")
        if _GPT_SOVITS_ROOT else ""
    )
    gpt_sovits_base_sovits_weights: str = (
        str(_GPT_SOVITS_ROOT / "GPT_SoVITS" / "pretrained_models" / "v2Pro" / "s2Gv2ProPlus.pth")
        if _GPT_SOVITS_ROOT else ""
    )
    # Only explicitly installed, per-voice adaptations are registered here.
    gpt_sovits_profiles_file: Path = ROOT / 'data' / 'voice_models' / 'profiles.json'
    # Preserve reference delivery, with complete-phrase checks and retry/fallback.
    gpt_sovits_clone_prompt_policy: Literal['off', 'checked'] = 'checked'
    # Mode 1 returns stable phrase-sized PCM fragments with the quality-first
    # decoder. The browser queues them without adding synthetic pauses.
    gpt_sovits_streaming_mode: int = 1
    # Live playback uses the progressive decoder. Keep this separate from the
    # compatibility setting above for callers that still request mode 1.
    gpt_sovits_live_streaming_mode: int = 2
    # AstraTTS keeps one mixed-language frontend pass alive for a stream. GPT-
    # SoVITS can approximate that behavior when it receives punctuation-aware
    # chunks with a larger semantic block.
    # The bundled runtime is a Chinese livestream and does not ship the
    # optional Japanese frontend dependency. Keep zh as the safe default;
    # operators with the full multilingual resource set may override it.
    gpt_sovits_live_text_language: str = "zh"
    gpt_sovits_live_text_split_method: str = "cut5"
    gpt_sovits_live_min_chunk_length: int = 16
    gpt_sovits_live_max_chars: int = 64
    # Uncalibrated fallback only. The local 2026-09-18 A/B found long silent
    # output after blindly lowering Xiadie's sampling; validated profiles win.
    gpt_sovits_clone_live_top_k: int = 18
    gpt_sovits_clone_live_top_p: float = 0.72
    gpt_sovits_clone_live_temperature: float = 0.66
    # v2ProPlus can retain acoustic timbre without semantic prompt tokens.
    # Live clones default to this path because ASR found reference-tail words
    # inserted in prompted streams. Other model families retain their prompt.
    gpt_sovits_live_use_prompt_text: bool = False
    gpt_sovits_live_seed_mode: Literal['fixed', 'text-low8'] = 'fixed'
    # Preserve the reference's delivery and the calibrated temperature.
    gpt_sovits_live_delivery: str = "natural"
    # Optional Live2D avatar assets. The default points to the supplied
    # Hu Tao model outside the repository; assets are served read-only by the
    # backend and are never copied into the source tree.
    live2d_model_root: str = str(_LIVE2D_ROOT) if _LIVE2D_ROOT else ""
    live2d_model_file: str = "Hu Tao.model3.json"
    live2d_enabled: bool = True
    max_document_bytes: int = 25 * 1024 * 1024
    max_audio_bytes: int = 50 * 1024 * 1024
    model_config = SettingsConfigDict(env_file=ROOT / "backend" / ".env", extra="ignore")

settings = Settings()
