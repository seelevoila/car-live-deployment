from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]

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
    # Select the server-side speech engine. IndexTTS-2.5 is the documented
    # default (see README and backend/.env.example); GPT-SoVITS stays selectable
    # with TTS_PROVIDER=gpt-sovits. `main._tts_provider()` also falls back to
    # IndexTTS2 for an empty value, so both defaults agree.
    tts_provider: str = "idextts2"
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
    gpt_sovits_python: str = str(ROOT.parent / "GPT-SoVITS" / ".venv" / "Scripts" / "python.exe")
    gpt_sovits_speaker_model: str = str(ROOT.parent / "GPT-SoVITS" / "GPT_SoVITS" / "pretrained_models" / "sv" / "pretrained_eres2netv2w24s4ep4.ckpt")
    gpt_sovits_aux_similarity_threshold: float = 0.85
    # The API process holds one GPT-SoVITS model at a time.  Keep the base
    # v2ProPlus pair available for newly cloned voices and the optional Xilian
    # fine-tune pair for the trained Xilian voice only.
    gpt_sovits_base_gpt_weights: str = str(ROOT.parent / "GPT-SoVITS" / "GPT_SoVITS" / "pretrained_models" / "s1v3.ckpt")
    gpt_sovits_base_sovits_weights: str = str(ROOT.parent / "GPT-SoVITS" / "GPT_SoVITS" / "pretrained_models" / "v2Pro" / "s2Gv2ProPlus.pth")
    gpt_sovits_xilian_gpt_weights: str = str(ROOT / "artifacts" / "xilian-dataset" / "weights" / "xilian_v2pro-e10.ckpt")
    gpt_sovits_xilian_sovits_weights: str = str(ROOT / "artifacts" / "xilian-dataset" / "weights" / "xilian_v2pro_e6_s588.pth")
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
    # Live clones use a bounded expressive floor. Earlier values (12/.58/.52)
    # removed pitch motion and made every speaker sound flat. The floor keeps
    # calibrated conservative profiles from collapsing while still bounding
    # runaway sampling.
    gpt_sovits_clone_live_top_k: int = 18
    gpt_sovits_clone_live_top_p: float = 0.72
    gpt_sovits_clone_live_temperature: float = 0.66
    # v2ProPlus can retain acoustic timbre without semantic prompt tokens.
    # Live clones default to this path because ASR found reference-tail words
    # inserted in prompted streams. Other model families retain their prompt.
    gpt_sovits_live_use_prompt_text: bool = False
    gpt_sovits_live_delivery: str = "warm"
    # IndexTTS-2.5 is the default engine and is deliberately configured
    # independently from GPT-SoVITS.  Either point at a running HTTP wrapper or
    # an official local IndexTTS2 checkout containing its checkpoints directory.
    # INDEX_TTS2_CONFIG and INDEX_TTS2_MODEL_DIR must name the *2.5* checkpoint
    # set: the adapter picks indextts.infer_v2_5 from the `version:` field of
    # config.yaml, and a 2.0 checkpoint set silently keeps the older engine.
    index_tts2_enabled: bool = True
    index_tts2_url: str = ""
    index_tts2_root: str = str(ROOT.parent / "IndexTTS2")
    index_tts2_python: str = str(ROOT.parent / "IndexTTS2" / ".venv" / "Scripts" / "python.exe")
    index_tts2_config: str = str(ROOT.parent / "IndexTTS2" / "checkpoints" / "config.yaml")
    index_tts2_model_dir: str = str(ROOT.parent / "IndexTTS2" / "checkpoints")
    index_tts2_use_fp16: bool = True
    index_tts2_ref_audio: str = ""
    index_tts2_prompt_text: str = ""
    # Optional Live2D avatar assets. The default points to the supplied
    # Hu Tao model outside the repository; assets are served read-only by the
    # backend and are never copied into the source tree.
    live2d_model_root: str = str(ROOT.parent / "原神")
    live2d_model_file: str = "Hu Tao.model3.json"
    live2d_enabled: bool = True
    max_document_bytes: int = 25 * 1024 * 1024
    max_audio_bytes: int = 50 * 1024 * 1024
    model_config = SettingsConfigDict(env_file=ROOT / "backend" / ".env", extra="ignore")

settings = Settings()
