"""IndexTTS-2/2.5 adapter.

IndexTTS is intentionally isolated from the GPT-SoVITS implementation. The
adapter supports the official 2.5 Python inference class, falls back to the
older 2.x class when needed, and supports a small HTTP mode for deployments
that run the model as a separate service.
"""

from __future__ import annotations

import base64
import importlib
import re
import sys
import subprocess
import threading
import uuid
import wave
from pathlib import Path
from typing import Any

import httpx


class IndexTTS2Unavailable(RuntimeError):
    pass


def normalize_index_tts2_version(value: Any) -> str | None:
    """Map a reported checkpoint version onto the published release names.

    The official checkout reports ``2`` for the 2.0 release and ``2.5`` for the
    2.5 release, while ``config.yaml`` carries the same numbers. Normalising to
    ``"2.0"``/``"2.5"`` keeps the API and the UI from advertising 2.5 while a
    2.0 checkpoint is loaded.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return text
    if number >= 2.5:
        return "2.5"
    if number >= 2.0:
        return "2.0"
    return text


def index_tts2_label(version: str | None) -> str:
    return f"IndexTTS-{version}" if version else "IndexTTS"


class IndexTTS2Engine:
    provider = "idextts2"
    # Fallback only: `status()` reports the version the configured engine
    # really serves, because a 2.0 deployment was previously labelled 2.5.
    label = "IndexTTS"

    def __init__(self, settings):
        self.settings = settings
        self._model = None
        self._model_version = None
        self._model_lock = threading.Lock()

    def _root(self) -> Path:
        return Path(self.settings.index_tts2_root).expanduser()

    def _local_configured(self) -> bool:
        root = self._root()
        return bool(
            self.settings.index_tts2_enabled
            and Path(self.settings.index_tts2_config).is_file()
            and Path(self.settings.index_tts2_model_dir).is_dir()
            and (Path(self.settings.index_tts2_python).is_file() or self._module_available(root))
        )

    @staticmethod
    def _module_available(root: Path) -> bool:
        return (root / "indextts").is_dir() or (root / "indextts2").is_dir()

    def _checkpoint_version(self) -> str:
        """Report the version that produced the configured checkpoints.

        The official checkout ships both the 2.0 and the 2.5 inference module,
        so importing one proves nothing about the weights on disk. Driving 2.0
        weights with the 2.5 text frontend indexes a 12k embedding table with
        58k tiktoken ids and aborts the CUDA context with a device-side assert.
        """
        try:
            text = Path(self.settings.index_tts2_config).read_text(encoding="utf-8")
        except OSError:
            return "2.5"
        match = re.search(r"(?m)^\s*version\s*:\s*([0-9]+(?:\.[0-9]+)?)", text)
        if not match:
            return "2.5"
        return "2.5" if float(match.group(1)) >= 2.5 else "2"

    def configured(self) -> bool:
        return bool(self.settings.index_tts2_enabled and (self.settings.index_tts2_url or self._local_configured()))

    def _http_base(self) -> str:
        return self.settings.index_tts2_url.rstrip("/")

    def _local_version(self) -> str:
        return normalize_index_tts2_version(self._checkpoint_version()) or "2.0"

    def _http_probe(self) -> tuple[bool, str | None]:
        """Return ``(reachable, model_version)`` for the configured wrapper.

        A lightweight wrapper may expose only POST /tts and answer GET with
        404/405, so any response below 500 still proves reachability. The
        version is only known when the wrapper answers /health with a JSON body
        that reports it, which is why the probe keeps looking when /health is
        absent.
        """
        base = self._http_base()
        reachable = False
        version: str | None = None
        for suffix in ("/health", "/docs", ""):
            try:
                with httpx.Client(timeout=1.5, trust_env=False) as client:
                    response = client.get(base + suffix)
            except httpx.HTTPError:
                continue
            if response.status_code >= 500:
                continue
            reachable = True
            if suffix == "/health":
                try:
                    body = response.json()
                except ValueError:
                    body = None
                if isinstance(body, dict):
                    version = normalize_index_tts2_version(body.get("version"))
            if version is not None:
                break
        return reachable, version

    def probe(self) -> bool:
        if not self.settings.index_tts2_enabled:
            return False
        if self.settings.index_tts2_url:
            return self._http_probe()[0]
        return self._local_configured()

    def model_version(self) -> str | None:
        """Version the configured engine actually serves, or None if unknown."""
        if not self.settings.index_tts2_enabled:
            return None
        if self.settings.index_tts2_url:
            return self._http_probe()[1]
        if self._local_configured():
            return self._local_version()
        return None

    def status(self) -> dict[str, Any]:
        configured = self.configured()
        version: str | None = None
        if configured and self.settings.index_tts2_url:
            reachable, version = self._http_probe()
        else:
            reachable = configured and self._local_configured()
            if reachable:
                version = self._local_version()
        return {
            "provider": self.provider,
            "label": index_tts2_label(version),
            "model_version": version,
            # Speed control is 2.5-only: `duration_factor` does not exist in the
            # 2.x inference signature, so a stream/synthesize request that only
            # carries GPT-style speed_factor is accepted and then dropped.
            "speed_control_supported": version == "2.5",
            "configured": configured,
            "reachable": reachable,
            "ready": configured and reachable,
            "mode": "http" if self.settings.index_tts2_url else "local",
            "endpoint": self.settings.index_tts2_url or None,
        }

    def _load_model(self):
        if self._model is not None:
            return self._model
        with self._model_lock:
            if self._model is not None:
                return self._model
            root = self._root()
            if root.is_dir() and str(root) not in sys.path:
                sys.path.insert(0, str(root))
            try:
                # The current official checkout exposes IndexTTS-2.5 through
                # infer_v2_5. Keep the older module as a fallback for existing
                # IndexTTS-2 installations.
                self._model_version = self._checkpoint_version()
                module = importlib.import_module(
                    "indextts.infer_v2_5" if self._model_version == "2.5"
                    else "indextts.infer_v2"
                )
                cls = getattr(module, "IndexTTS2")
            except (ImportError, AttributeError) as exc:
                raise IndexTTS2Unavailable(
                    "未找到 IndexTTS-2/2.5 Python 推理包，请配置 INDEX_TTS2_ROOT 或 INDEX_TTS2_URL"
                ) from exc
            try:
                kwargs = {
                    "cfg_path": str(self.settings.index_tts2_config),
                    "model_dir": str(self.settings.index_tts2_model_dir),
                    # CUDA kernel requires ninja compilation; disabled for compatibility
                    "use_cuda_kernel": False,
                    "use_deepspeed": False,
                    "use_qwen_emo": False,
                }
                if self._model_version == "2.5":
                    kwargs["use_bf16"] = bool(self.settings.index_tts2_use_fp16)
                else:
                    kwargs["use_fp16"] = bool(self.settings.index_tts2_use_fp16)
                self._model = cls(**kwargs)
            except TypeError:
                # Older IndexTTS2 checkouts do not expose the optional kernel
                # switches. Keep the adapter compatible with both signatures.
                fallback = {
                    "cfg_path": str(self.settings.index_tts2_config),
                    "model_dir": str(self.settings.index_tts2_model_dir),
                }
                if self._model_version == "2.5":
                    fallback["use_bf16"] = bool(self.settings.index_tts2_use_fp16)
                else:
                    fallback["use_fp16"] = bool(self.settings.index_tts2_use_fp16)
                self._model = cls(**fallback)
            return self._model

    @staticmethod
    def _wav_bytes(path: Path) -> bytes:
        if not path.is_file() or path.stat().st_size < 44:
            raise IndexTTS2Unavailable("IndexTTS2 未生成有效 WAV 音频")
        with wave.open(str(path), "rb") as audio:
            if audio.getsampwidth() != 2 or audio.getnchannels() < 1:
                raise IndexTTS2Unavailable("IndexTTS2 输出不是 16-bit PCM WAV")
            return path.read_bytes()

    def _infer_local(self, *, text: str, reference_audio: str, speed_factor: float) -> bytes:
        output = Path(self.settings.upload_dir) / "idextts2" / f"{uuid.uuid4().hex}.wav"
        output.parent.mkdir(parents=True, exist_ok=True)
        try:
            model = self._load_model()
        except IndexTTS2Unavailable:
            return self._infer_subprocess(
                text=text,
                reference_audio=reference_audio,
                output=output,
                speed_factor=speed_factor,
            )
        kwargs = {
            "spk_audio_prompt": reference_audio,
            "text": text,
            "output_path": str(output),
            "use_random": False,
        }
        if self._model_version == "2.5":
            kwargs["lang"] = self._language_for_text(text)
            kwargs["duration_factor"] = self._duration_factor(speed_factor)
        # IndexTTS2 uses emotion conditioning. For live broadcast, use low
        # emotion blending (0.3) to prioritize natural, stable delivery.
        # Higher values can sound theatrical; 0.0 sounds flat.
        kwargs["emo_alpha"] = 0.3
        try:
            model.infer(**kwargs)
        except TypeError:
            kwargs.pop("emo_alpha", None)
            kwargs.pop("use_random", None)
            model.infer(**kwargs)
        try:
            return self._wav_bytes(output)
        finally:
            output.unlink(missing_ok=True)

    @staticmethod
    def _duration_factor(speed_factor: float) -> float:
        """Convert the app's GPT-style speed_factor into IndexTTS duration_factor.

        The app exposes ``speed_factor`` (larger is faster), while IndexTTS-2.5
        exposes ``duration_factor`` (larger is slower, valid range 0.5-2.0).
        """
        try:
            value = float(speed_factor)
        except (TypeError, ValueError):
            value = 1.0
        return max(0.5, min(2.0, 1.0 / max(0.6, min(1.6, value))))

    @staticmethod
    def _language_for_text(text: str) -> str:
        """Pick the IndexTTS-2.5 ``lang`` code for *text*.

        IndexTTS-2.5 ships zh/en/ja/es/ar. The official tokenizer records
        Japanese as ``ja``; ``lang_to_token()`` silently falls back to
        ``common`` for an unknown code, so a wrong code degrades quality without
        raising. Codes are matched case-insensitively by the tokenizer.
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

    def _infer_subprocess(self, *, text: str, reference_audio: str, output: Path, speed_factor: float = 1.0) -> bytes:
        """Use the configured IndexTTS2 virtualenv when backend Python lacks it."""
        python = Path(self.settings.index_tts2_python)
        if not python.is_file():
            raise IndexTTS2Unavailable("未找到 IndexTTS2 Python 运行环境")
        script = (
            "import sys\n"
            "V25 = sys.argv[6] == '2.5'\n"
            "if V25:\n"
            "    from indextts.infer_v2_5 import IndexTTS2\n"
            "else:\n"
            "    from indextts.infer_v2 import IndexTTS2\n"
            "model = IndexTTS2(cfg_path=sys.argv[1], model_dir=sys.argv[2])\n"
            "kwargs = {'spk_audio_prompt': sys.argv[3], 'text': sys.argv[4], 'output_path': sys.argv[5], 'use_random': False}\n"
            "if V25:\n"
            "    kwargs.update(lang=sys.argv[7], duration_factor=float(sys.argv[8]))\n"
            "model.infer(**kwargs)\n"
        )
        os = __import__("os")
        env = dict(os.environ)
        root = str(self._root())
        env["PYTHONPATH"] = root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        try:
            result = subprocess.run(
                [
                    str(python), "-c", script,
                    str(self.settings.index_tts2_config),
                    str(self.settings.index_tts2_model_dir),
                    reference_audio,
                    text,
                    str(output),
                    self._checkpoint_version(),
                    self._language_for_text(text),
                    str(self._duration_factor(speed_factor)),
                ],
                capture_output=True,
                text=True,
                timeout=180,
                env=env,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise IndexTTS2Unavailable(f"IndexTTS2 推理进程启动失败：{exc}") from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()[-500:]
            raise IndexTTS2Unavailable(f"IndexTTS2 推理失败：{detail}")
        try:
            return self._wav_bytes(output)
        finally:
            output.unlink(missing_ok=True)

    def _infer_http(self, *, text: str, reference_audio: str, speed_factor: float) -> bytes:
        payload = {
            "text": text,
            "spk_audio_prompt": reference_audio,
            "speaker_audio": reference_audio,
            # Use low emotion blending for natural broadcast delivery
            "emo_alpha": 0.3,
            "use_random": False,
            "speed_factor": speed_factor,
            "lang": self._language_for_text(text),
            "duration_factor": self._duration_factor(speed_factor),
        }
        # A remote wrapper cannot read the backend's Windows path. Supplying
        # the optional base64 form lets such wrappers accept the same request
        # without mounting the uploads directory.
        try:
            payload["speaker_audio_base64"] = base64.b64encode(Path(reference_audio).read_bytes()).decode("ascii")
        except OSError:
            pass
        endpoint = self._http_base()
        if not endpoint.endswith("/tts"):
            endpoint += "/tts"
        try:
            with httpx.Client(timeout=180, trust_env=False) as client:
                response = client.post(endpoint, json=payload)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise IndexTTS2Unavailable(f"IndexTTS2 服务调用失败：{exc}") from exc
        content_type = response.headers.get("content-type", "")
        if "audio" in content_type or response.content[:4] == b"RIFF":
            return response.content
        try:
            body = response.json()
        except ValueError as exc:
            raise IndexTTS2Unavailable("IndexTTS2 服务未返回 WAV 音频") from exc
        encoded = body.get("audio") or body.get("audio_base64") or body.get("wav")
        if isinstance(encoded, str):
            if encoded.startswith("data:"):
                encoded = encoded.split(",", 1)[-1]
            try:
                return base64.b64decode(encoded)
            except (ValueError, TypeError) as exc:
                raise IndexTTS2Unavailable("IndexTTS2 返回的音频编码无效") from exc
        output_path = body.get("output_path") or body.get("audio_path")
        if output_path and Path(output_path).is_file():
            return Path(output_path).read_bytes()
        raise IndexTTS2Unavailable("IndexTTS2 服务未返回 WAV 音频")

    def synthesize(self, *, text: str, reference_audio: str, speed_factor: float = 1.0) -> bytes:
        if not self.settings.index_tts2_enabled:
            raise IndexTTS2Unavailable("IndexTTS2 已禁用")
        if self.settings.index_tts2_url:
            return self._infer_http(text=text, reference_audio=reference_audio, speed_factor=speed_factor)
        if not self._local_configured():
            raise IndexTTS2Unavailable(
                "IndexTTS2 未就绪，请配置 INDEX_TTS2_ROOT、INDEX_TTS2_CONFIG 和 INDEX_TTS2_MODEL_DIR，或设置 INDEX_TTS2_URL"
            )
        return self._infer_local(text=text, reference_audio=reference_audio, speed_factor=speed_factor)

    def warmup(self, reference_audio: str | None, *, text: str = "你好。") -> bool:
        if not reference_audio:
            return False
        self.synthesize(text=text, reference_audio=reference_audio)
        return True
