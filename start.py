#!/usr/bin/env python3
"""Cross-platform launcher for the frontend, FastAPI backend, and GPT-SoVITS.

The launcher refuses to take over an unrelated process. Existing project
processes on the managed ports are stopped before a fresh start.
"""

from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOGS_DIR = ROOT / "logs"
MANAGED_PORTS = {8000: "backend", 5173: "frontend", 9881: "gpt-sovits"}


def find_python() -> Path:
    current = Path(sys.executable).resolve()
    in_project_env = bool(os.environ.get("VIRTUAL_ENV")) or any(part in {".venv", "venv"} for part in current.parts)
    candidates = [
        current if in_project_env else None,
        ROOT / ".venv" / "Scripts" / "python.exe",
        ROOT / ".venv" / "bin" / "python",
        ROOT / "venv" / "Scripts" / "python.exe",
        ROOT / "venv" / "bin" / "python",
    ]
    for candidate in candidates:
        if candidate and candidate.is_file():
            return candidate
    if current.exists():
        print("Warning: no project virtual environment detected; using the current Python.")
        return current
    raise SystemExit("Python 3.12 is required. Run: python -m venv .venv && install the dependencies.")


def ensure_rag_models(python: Path) -> None:
    """Materialize and verify the repository-bundled RAG models before startup."""
    setup_script = ROOT / "scripts" / "setup_rag_models.py"
    result = subprocess.run([str(python), str(setup_script)], cwd=ROOT, check=False)
    if result.returncode:
        raise RuntimeError(
            "RAG model setup failed; run scripts/setup_rag_models.py manually and inspect its output"
        )


def find_gpt_sovits() -> tuple[Path | None, Path | None]:
    configured = os.environ.get("GPT_SOVITS_ROOT")
    candidates = [Path(configured)] if configured else []
    candidates.extend(ROOT.parent / name for name in ("GPT-SoVITS-v2pro-20250604", "GPT-SoVITS", "gpt-sovits"))
    for root in candidates:
        if not root or not root.is_dir():
            continue
        for name in ("runtime/python.exe", "runtime/python", ".venv/Scripts/python.exe", ".venv/bin/python"):
            interpreter = root / name
            if interpreter.is_file():
                return root, interpreter
    return None, None


def port_open(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.4)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def port_pids(port: int) -> list[int]:
    if os.name == "nt":
        result = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"], capture_output=True, text=True, check=False
        )
        pids = []
        for line in result.stdout.splitlines():
            fields = line.split()
            if len(fields) >= 5 and fields[0].upper() == "TCP" and fields[1].endswith(f":{port}") and fields[3].upper() == "LISTENING":
                try:
                    pids.append(int(fields[4]))
                except ValueError:
                    pass
        return sorted(set(pids))
    if shutil.which("lsof"):
        result = subprocess.run(["lsof", "-nP", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"], capture_output=True, text=True, check=False)
        return sorted({int(value) for value in result.stdout.split() if value.isdigit()})
    if shutil.which("fuser"):
        result = subprocess.run(["fuser", "-n", "tcp", str(port)], capture_output=True, text=True, check=False)
        return sorted({int(value) for value in result.stdout.split() if value.isdigit()})
    return []


def process_command(pid: int) -> str:
    if os.name == "nt":
        command = ["powershell", "-NoProfile", "-Command", f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine"]
    else:
        command = ["ps", "-p", str(pid), "-o", "args="]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    return result.stdout.strip()


def is_known_process(service: str, command: str) -> bool:
    tokens = {
        "backend": ("uvicorn app.main:app", "start.py"),
        "frontend": ("http.server 5173", "start.py"),
        "gpt-sovits": ("gpt_sovits_api.py", "api_v2.py"),
    }[service]
    return any(token in command for token in tokens)


def terminate(pid: int) -> None:
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], check=False, capture_output=True)
        else:
            os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass


def ensure_port_free(port: int, service: str) -> None:
    pids = port_pids(port)
    if not pids:
        if port_open(port):
            raise RuntimeError(f"{service} port {port} is occupied, but its owner could not be identified")
        return
    for pid in pids:
        command = process_command(pid)
        if not is_known_process(service, command):
            raise RuntimeError(f"port {port} is occupied by an unrelated process (PID {pid}): {command}")
        print(f"Stopping existing {service} process {pid} on port {port}")
        terminate(pid)
    for _ in range(40):
        if not port_open(port):
            return
        time.sleep(0.25)
    raise RuntimeError(f"could not release {service} port {port}")


def wait_port(port: int, timeout: int) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if port_open(port):
            return True
        time.sleep(1)
    return False


def start_service(name: str, command: list[str], cwd: Path) -> subprocess.Popen:
    LOGS_DIR.mkdir(exist_ok=True)
    log = (LOGS_DIR / f"{name}.log").open("w", encoding="utf-8")
    print(f"Starting {name} (log: {log.name}) ...")
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    process = subprocess.Popen(command, cwd=cwd, stdout=log, stderr=subprocess.STDOUT, creationflags=creationflags)
    process._codex_log = log  # type: ignore[attr-defined]
    return process


def stop_process(process: subprocess.Popen | None) -> None:
    if not process or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def main() -> int:
    python = find_python()
    ensure_rag_models(python)
    for port, service in MANAGED_PORTS.items():
        if service == "gpt-sovits":
            continue
        ensure_port_free(port, service)

    processes: list[subprocess.Popen] = []
    try:
        backend = start_service("backend", [str(python), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"], ROOT / "backend")
        frontend = start_service("frontend", [str(python), "-m", "http.server", "5173", "--bind", "127.0.0.1"], ROOT / "frontend")
        processes.extend((backend, frontend))

        gpt_root, gpt_python = find_gpt_sovits()
        gpt_process = None
        required = (
            "GPT_SoVITS/pretrained_models/s1v3.ckpt",
            "GPT_SoVITS/pretrained_models/v2Pro/s2Gv2ProPlus.pth",
            "GPT_SoVITS/pretrained_models/sv/pretrained_eres2netv2w24s4ep4.ckpt",
        )
        if gpt_root and gpt_python and (gpt_root / "api_v2.py").is_file() and all((gpt_root / path).is_file() for path in required):
            ensure_port_free(9881, "gpt-sovits")
            gpt_process = start_service(
                "gpt-sovits",
                [str(gpt_python), str(ROOT / "scripts" / "gpt_sovits_api.py"), "--gpt-root", str(gpt_root), "-a", "127.0.0.1", "-p", "9881", "-c", str(gpt_root / "GPT_SoVITS" / "configs" / "tts_infer.yaml")],
                gpt_root,
            )
            processes.append(gpt_process)
        else:
            print("GPT-SoVITS not found or required weights are missing; TTS will report the missing external runtime.")

        if not wait_port(8000, 20):
            raise RuntimeError("backend failed; inspect logs/backend.log")
        if not wait_port(5173, 20):
            raise RuntimeError("frontend failed; inspect logs/frontend.log")
        if gpt_process and not wait_port(9881, 120):
            print("GPT-SoVITS is still loading or failed; inspect logs/gpt-sovits.log", file=sys.stderr)

        print("\nServices started:")
        print("  Frontend: http://127.0.0.1:5173")
        print("  Backend:  http://127.0.0.1:8000/docs")
        if gpt_process:
            print("  GPT-SoVITS: http://127.0.0.1:9881")
        print("Logs: logs/backend.log, logs/frontend.log, logs/gpt-sovits.log")
        print("Press Ctrl+C to stop all services.")
        while True:
            time.sleep(1)
            if any(process.poll() is not None for process in processes[:2]):
                raise RuntimeError("backend or frontend exited unexpectedly")
    except KeyboardInterrupt:
        print("\nStopping services...")
        return 0
    finally:
        for process in reversed(processes):
            stop_process(process)
            log = getattr(process, "_codex_log", None)
            if log:
                log.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)
