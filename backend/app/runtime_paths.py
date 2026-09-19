"""Cross-platform runtime path detection for external dependencies.

Explores standard locations and environment variables to locate GPT-SoVITS,
Live2D assets, and ffmpeg without hardcoding absolute paths or
Windows-specific directory layouts.
"""
import os
import shutil
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent.parent  # project root


def _detect_venv_python(root: Path) -> Optional[Path]:
    """Detect Python interpreter in a virtual environment (cross-platform)."""
    candidates = [
        root / "runtime" / "python.exe",  # GPT-SoVITS v2pro bundled runtime
        root / "runtime" / "python",      # Linux bundled runtime
        root / ".venv" / "Scripts" / "python.exe",  # Windows venv
        root / ".venv" / "bin" / "python",          # Linux/macOS venv
        root / "venv" / "Scripts" / "python.exe",
        root / "venv" / "bin" / "python",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def detect_gpt_sovits_root() -> Optional[Path]:
    """Detect GPT-SoVITS installation root."""
    if env_root := os.environ.get("GPT_SOVITS_ROOT"):
        path = Path(env_root)
        if path.is_dir():
            logger.info(f"GPT-SoVITS root from GPT_SOVITS_ROOT: {path}")
            return path

    # Search standard locations relative to project
    candidates = [
        "GPT-SoVITS-v2pro-20250604",
        "GPT-SoVITS-v2pro",
        "GPT-SoVITS",
        "gpt-sovits",
    ]
    for name in candidates:
        path = ROOT.parent / name
        if path.is_dir():
            logger.info(f"GPT-SoVITS root auto-detected: {path}")
            return path

    logger.warning("GPT-SoVITS root not found. Set GPT_SOVITS_ROOT environment variable.")
    return None


def detect_gpt_sovits_python() -> Optional[Path]:
    """Detect GPT-SoVITS Python interpreter."""
    if env_python := os.environ.get("GPT_SOVITS_PYTHON"):
        path = Path(env_python)
        if path.is_file():
            return path

    root = detect_gpt_sovits_root()
    if not root:
        return None

    python = _detect_venv_python(root)
    if python:
        logger.info(f"GPT-SoVITS Python: {python}")
    else:
        logger.warning(f"No Python interpreter found in {root}")
    return python


def speaker_model_root(python: Path, checkpoint: Path) -> Path:
    """Resolve both bundled-runtime and venv layouts by the required source."""
    candidates = [*python.resolve().parents, *checkpoint.resolve().parents]
    detected = detect_gpt_sovits_root()
    if detected:
        candidates.append(detected)
    for root in dict.fromkeys(candidates):
        if (root / 'GPT_SoVITS' / 'eres2net' / 'ERes2NetV2.py').is_file():
            return root
    raise FileNotFoundError('找不到 GPT_SoVITS/eres2net/ERes2NetV2.py，无法进行音色评分')


def detect_live2d_model_root() -> Optional[Path]:
    """Detect Live2D model directory."""
    if env_root := os.environ.get("LIVE2D_MODEL_ROOT"):
        path = Path(env_root)
        if path.is_dir():
            return path

    candidates = [
        ROOT.parent / "原神",
        ROOT.parent / "Live2D",
        ROOT.parent / "models" / "live2d",
        ROOT / "assets" / "live2d",
    ]
    for path in candidates:
        if path.is_dir():
            logger.info(f"Live2D model root: {path}")
            return path

    return None


def detect_ffmpeg() -> Optional[Path]:
    """Detect ffmpeg binary."""
    if env_bin := os.environ.get("FFMPEG_BIN"):
        path = Path(env_bin)
        if path.is_file():
            return path

    # Check PATH first
    if ffmpeg := shutil.which("ffmpeg"):
        return Path(ffmpeg)

    # Check GPT-SoVITS runtime
    gpt_root = detect_gpt_sovits_root()
    if gpt_root:
        candidates = [
            gpt_root / "runtime" / "ffmpeg.exe",
            gpt_root / "runtime" / "ffmpeg",
        ]
        for candidate in candidates:
            if candidate.is_file():
                return candidate

    return None


def get_runtime_paths() -> dict:
    """Get all detected runtime paths as a dictionary for logging/status."""
    return {
        "gpt_sovits_root": detect_gpt_sovits_root(),
        "gpt_sovits_python": detect_gpt_sovits_python(),
        "live2d_model_root": detect_live2d_model_root(),
        "ffmpeg": detect_ffmpeg(),
    }
