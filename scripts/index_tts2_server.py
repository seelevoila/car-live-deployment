"""Persistent HTTP wrapper around the official IndexTTS-2/2.5 model.

The application backend keeps its own virtualenv, so this process owns the
IndexTTS model and keeps it resident in GPU memory between requests. Clicking
preview therefore never starts a fresh multi-gigabyte Python process.

This file is the in-repository copy used by `start.ps1`. It must be launched
with the IndexTTS2 virtualenv (`INDEX_TTS2_PYTHON`), because it imports
`indextts` from the official checkout.

    python index_tts2_server.py \
        --cfg-path <checkpoints>/config.yaml --model-dir <checkpoints> \
        --host 127.0.0.1 --port 8001

The served checkpoint version is selected from the `version:` field of
config.yaml: 2.0 weights must not be driven by the 2.5 text frontend, because
that indexes a 12k embedding table with 58k tiktoken ids and aborts the CUDA
context with a device-side assert.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import tempfile
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Add IndexTTS root to Python path if launched from repository
# The INDEX_TTS2_ROOT env var should point to the IndexTTS checkout
index_root = os.environ.get('INDEX_TTS2_ROOT')
if index_root and os.path.isdir(index_root) and str(index_root) not in sys.path:
    sys.path.insert(0, str(index_root))


def checkpoint_version(cfg_path: str) -> str:
    """Pick the inference module that matches the installed checkpoints.

    The official checkout ships both the 2.0 and the 2.5 module, so a
    successful import proves nothing about the weights on disk; `config.yaml`
    records the version that produced the checkpoint.
    """
    try:
        text = Path(cfg_path).read_text(encoding="utf-8")
    except OSError:
        return "2.5"
    match = re.search(r"(?m)^\s*version\s*:\s*([0-9]+(?:\.[0-9]+)?)", text)
    if not match:
        return "2.5"
    return "2.5" if float(match.group(1)) >= 2.5 else "2"


def release_name(version: str) -> str:
    """Map the internal module selector onto the published release name."""
    return "2.5" if version == "2.5" else "2.0"


def ensure_package_importable(model_dir: str) -> None:
    """Put the official IndexTTS checkout on ``sys.path``.

    This wrapper lives in the application repository, not in the model checkout,
    so Python puts *this* directory (``scripts/``) on ``sys.path`` and never the
    checkout. INDEX_TTS2_ROOT covers the launcher case; --model-dir covers
    everything else.
    """
    resolved = Path(model_dir).resolve()
    for candidate in (resolved.parent, resolved):
        if (candidate / "indextts").is_dir():
            if str(candidate) not in sys.path:
                sys.path.insert(0, str(candidate))
            return
    raise SystemExit(
        f"未在 {resolved} 或其上级目录找到 indextts 包，请确认 --model-dir 指向 IndexTTS checkout"
    )


def load_engine_class(version: str):
    if version == "2.5":
        from indextts.infer_v2_5 import IndexTTS2
    else:
        from indextts.infer_v2 import IndexTTS2
    return IndexTTS2


class IndexTTS2Server:
    def __init__(self, cfg_path: str, model_dir: str, use_fp16: bool = True, use_accel: bool = False):
        kwargs = {
            "cfg_path": cfg_path,
            "model_dir": model_dir,
            # CUDA kernel requires ninja compilation; disabled for compatibility
            "use_cuda_kernel": False,
            "use_deepspeed": False,
            # The live studio supplies a neutral emotion vector and does not
            # use text-to-emotion guidance. Avoid loading the extra Qwen model
            # so the resident service leaves more VRAM for the desktop.
            "use_qwen_emo": False,
            # Enable GPT2 acceleration if available (flash_attn)
            "use_accel": use_accel,
        }
        self.version = checkpoint_version(cfg_path)
        engine_class = load_engine_class(self.version)
        kwargs["use_bf16" if self.version == "2.5" else "use_fp16"] = use_fp16
        try:
            self.model = engine_class(**kwargs)
        except TypeError:
            self.model = engine_class(cfg_path=cfg_path, model_dir=model_dir)
        self.infer_lock = threading.Lock()

    def synthesize(self, payload: dict) -> bytes:
        text = str(payload.get("text") or "").strip()
        if not text:
            raise ValueError("text is required")

        reference = str(payload.get("spk_audio_prompt") or payload.get("speaker_audio") or "")
        temporary_reference = None
        if not Path(reference).is_file():
            encoded = payload.get("speaker_audio_base64")
            if not isinstance(encoded, str) or not encoded:
                raise FileNotFoundError("speaker audio was not found")
            if encoded.startswith("data:"):
                encoded = encoded.split(",", 1)[-1]
            fd, temporary_reference = tempfile.mkstemp(suffix=".wav")
            with os.fdopen(fd, "wb") as stream:
                stream.write(base64.b64decode(encoded))
            reference = temporary_reference

        fd, output = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            kwargs = {
                "spk_audio_prompt": reference,
                "text": text,
                "output_path": output,
                # For live broadcast, use low emotion blending (0.3) to
                # prioritize natural, stable delivery. Payload can override.
                "emo_vector": payload.get("emo_vector") or None,
                "emo_alpha": float(payload.get("emo_alpha", 0.3)),
                "use_random": False,
            }
            if self.version == "2.5":
                kwargs["lang"] = str(payload.get("lang") or self._language_for_text(text))
                kwargs["duration_factor"] = max(
                    0.5, min(2.0, float(payload.get("duration_factor", 1.0)))
                )
            with self.infer_lock:
                self.model.infer(**kwargs)
            path = Path(output)
            if not path.is_file() or path.stat().st_size < 44:
                raise RuntimeError("IndexTTS2 did not create a valid WAV")
            with wave.open(str(path), "rb") as audio:
                if audio.getsampwidth() != 2 or audio.getnchannels() < 1:
                    raise RuntimeError("IndexTTS2 output is not 16-bit PCM WAV")
            return path.read_bytes()
        finally:
            Path(output).unlink(missing_ok=True)
            if temporary_reference:
                Path(temporary_reference).unlink(missing_ok=True)

    @staticmethod
    def _language_for_text(text: str) -> str:
        """Pick the IndexTTS-2.5 ``lang`` code for *text*.

        IndexTTS-2.5 ships zh/en/ja/es/ar. The official tokenizer records
        Japanese as ``ja``; ``lang_to_token()`` silently falls back to
        ``common`` for an unknown code, so a wrong code degrades quality
        without raising. Codes are matched case-insensitively by the tokenizer.
        """
        if any("\u3040" <= char <= "\u30ff" for char in text):
            return "ja"
        if any("\u4e00" <= char <= "\u9fff" for char in text):
            return "ZH"
        if any(
            "\u0600" <= char <= "\u06ff"      # Arabic
            or "\u0750" <= char <= "\u077f"   # Arabic Supplement
            or "\u08a0" <= char <= "\u08ff"   # Arabic Extended-A
            or "\ufb50" <= char <= "\ufdff"   # Arabic Presentation Forms-A
            or "\ufe70" <= char <= "\ufeff"   # Arabic Presentation Forms-B
            for char in text
        ):
            return "AR"
        if any(char in "ñÑ¿¡áéíóúÁÉÍÓÚ" for char in text):
            return "ES"
        return "EN"


def make_handler(engine: IndexTTS2Server):
    class Handler(BaseHTTPRequestHandler):
        server_version = "IndexTTS2Server/1.0"

        def _send_json(self, status: int, body: dict):
            raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):  # noqa: N802
            if self.path.rstrip("/") in {"", "/health"}:
                self._send_json(200, {
                    "status": "ok",
                    "model_loaded": True,
                    "device": str(engine.model.device),
                    # Published release name, so /api/tts/status and the UI can
                    # never advertise 2.5 while 2.0 weights are resident.
                    "version": release_name(engine.version),
                    "speed_control": engine.version == "2.5",
                })
                return
            self._send_json(404, {"error": "not found"})

        def do_POST(self):  # noqa: N802
            if self.path.rstrip("/") != "/tts":
                self._send_json(404, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 80 * 1024 * 1024:
                    raise ValueError("invalid request size")
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                audio = engine.synthesize(payload)
                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                self.send_header("Content-Length", str(len(audio)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(audio)
            except Exception as exc:  # keep the worker alive after one bad request
                self._send_json(500, {"error": str(exc)[-500:]})

        def log_message(self, fmt, *args):
            print(f"[{self.log_date_time_string()}] {self.address_string()} {fmt % args}", flush=True)

    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cfg-path", default="checkpoints/config.yaml")
    parser.add_argument("--model-dir", default="checkpoints")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--no-fp16", action="store_true")
    args = parser.parse_args()
    ensure_package_importable(args.model_dir)
    engine = IndexTTS2Server(args.cfg_path, args.model_dir, use_fp16=not args.no_fp16)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(engine))
    print(
        f"IndexTTS2 {release_name(engine.version)} ready on http://{args.host}:{args.port} "
        f"({engine.model.device})",
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
