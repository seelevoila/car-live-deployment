#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$ROOT/logs"
mkdir -p "$LOG_DIR"

find_python() {
  if [[ -x "$ROOT/.venv/bin/python" ]]; then
    printf '%s\n' "$ROOT/.venv/bin/python"
  elif [[ -x "$ROOT/venv/bin/python" ]]; then
    printf '%s\n' "$ROOT/venv/bin/python"
  elif command -v python3 >/dev/null 2>&1; then
    command -v python3
  elif command -v python >/dev/null 2>&1; then
    command -v python
  else
    return 1
  fi
}

PYTHON="$(find_python || true)"
if [[ -z "$PYTHON" ]]; then
  echo "Error: Python 3.12 is required. Run: python3.12 -m venv .venv && .venv/bin/pip install -e ." >&2
  exit 1
fi

port_pids() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -t -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | sort -u
    return
  fi
  if command -v ss >/dev/null 2>&1; then
    ss -ltnpH 2>/dev/null | awk -v port=":${port}" '$4 ~ port"$" {match($0,/pid=[0-9]+/); if (RSTART) print substr($0,RSTART+4,RLENGTH-4)}' | sort -u
    return
  fi
  if command -v fuser >/dev/null 2>&1; then
    fuser -n tcp "$port" 2>/dev/null | tr ' ' '\n' | sed '/^$/d' | sort -u
  fi
}

port_open() {
  "$PYTHON" - "$1" <<'PY'
import socket, sys
with socket.socket() as sock:
    sock.settimeout(0.4)
    raise SystemExit(0 if sock.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0 else 1)
PY
}

ensure_port() {
  local port="$1" service="$2"
  local pids pid command
  pids="$(port_pids "$port" || true)"
  if [[ -z "$pids" ]]; then
    if port_open "$port"; then
      echo "Error: $service port $port is occupied, but its owner cannot be identified. Stop it manually." >&2
      exit 1
    fi
    return
  fi
  while IFS= read -r pid; do
    [[ -z "$pid" ]] && continue
    command="$(ps -p "$pid" -o args= 2>/dev/null || true)"
    case "$service:$command" in
      "backend:"*"uvicorn app.main:app"*|"backend:"*"start.py"*) ;;
      "frontend:"*"http.server 5173"*|"frontend:"*"start.py"*) ;;
      "gpt-sovits:"*"gpt_sovits_api.py"*|"gpt-sovits:"*"api_v2.py"*) ;;
      *)
        echo "Error: port $port is occupied by an unrelated process (PID $pid): $command" >&2
        exit 1
        ;;
    esac
    echo "Stopping existing $service process $pid on port $port"
    kill "$pid" 2>/dev/null || true
  done <<< "$pids"
  for _ in {1..20}; do
    port_open "$port" || return
    sleep 0.25
  done
  echo "Error: could not release $service port $port" >&2
  exit 1
}

wait_port() {
  local port="$1" timeout="$2"
  for _ in $(seq 1 "$timeout"); do
    port_open "$port" && return 0
    sleep 1
  done
  return 1
}

start_service() {
  local name="$1" cwd="$2"
  shift 2
  echo "Starting $name (log: logs/$name.log) ..." >&2
  (cd "$cwd" && nohup "$@" >"$LOG_DIR/$name.log" 2>&1 & echo $!)
}

ensure_port 8000 backend
ensure_port 5173 frontend

BACKEND_PID="$(start_service backend "$ROOT/backend" "$PYTHON" -m uvicorn app.main:app --host 127.0.0.1 --port 8000)"
FRONTEND_PID="$(start_service frontend "$ROOT/frontend" "$PYTHON" -m http.server 5173 --bind 127.0.0.1)"

GPT_ROOT="${GPT_SOVITS_ROOT:-}"
if [[ -z "$GPT_ROOT" ]]; then
  for candidate in "$ROOT/../GPT-SoVITS-v2pro-20250604" "$ROOT/../GPT-SoVITS" "$ROOT/../gpt-sovits"; do
    if [[ -d "$candidate" ]]; then GPT_ROOT="$candidate"; break; fi
  done
fi

GPT_PYTHON=""
if [[ -n "$GPT_ROOT" ]]; then
  for candidate in "$GPT_ROOT/runtime/python" "$GPT_ROOT/runtime/python.exe" "$GPT_ROOT/.venv/bin/python" "$GPT_ROOT/.venv/Scripts/python.exe"; do
    if [[ -x "$candidate" || -f "$candidate" ]]; then GPT_PYTHON="$candidate"; break; fi
  done
fi

GPT_PID=""
if [[ -n "$GPT_ROOT" && -n "$GPT_PYTHON" && -f "$GPT_ROOT/api_v2.py" ]]; then
  required=(
    "$GPT_ROOT/GPT_SoVITS/pretrained_models/s1v3.ckpt"
    "$GPT_ROOT/GPT_SoVITS/pretrained_models/v2Pro/s2Gv2ProPlus.pth"
    "$GPT_ROOT/GPT_SoVITS/pretrained_models/sv/pretrained_eres2netv2w24s4ep4.ckpt"
  )
  missing=()
  for path in "${required[@]}"; do [[ -f "$path" ]] || missing+=("$path"); done
  if ((${#missing[@]})); then
    echo "GPT-SoVITS is present but required weights are missing; see README.md." >&2
  else
    ensure_port 9881 gpt-sovits
    GPT_PID="$(start_service gpt-sovits "$GPT_ROOT" "$GPT_PYTHON" "$ROOT/scripts/gpt_sovits_api.py" --gpt-root "$GPT_ROOT" -a 127.0.0.1 -p 9881 -c "$GPT_ROOT/GPT_SoVITS/configs/tts_infer.yaml")"
  fi
else
  echo "GPT-SoVITS not found or disabled. TTS will report the missing external runtime." >&2
fi

if ! wait_port 8000 20; then echo "Backend failed; inspect logs/backend.log" >&2; exit 1; fi
if ! wait_port 5173 20; then echo "Frontend failed; inspect logs/frontend.log" >&2; exit 1; fi
if [[ -n "$GPT_PID" ]] && ! wait_port 9881 120; then
  echo "GPT-SoVITS is still loading or failed; inspect logs/gpt-sovits.log" >&2
fi

echo ""
echo "Services started:"
echo "  Frontend: http://127.0.0.1:5173"
echo "  Backend:  http://127.0.0.1:8000/docs"
if [[ -n "$GPT_PID" ]]; then echo "  GPT-SoVITS: http://127.0.0.1:9881"; fi
echo "Logs: logs/backend.log, logs/frontend.log, logs/gpt-sovits.log"
echo "Stop: kill $BACKEND_PID $FRONTEND_PID${GPT_PID:+ $GPT_PID}"
