#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export PYTHONPATH="$(pwd)${PYTHONPATH:+:$PYTHONPATH}"
PYTHON_BIN="${EDGE_SUPPORT_PYTHON:-.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Run bash scripts/setup.sh first, or set EDGE_SUPPORT_PYTHON to your Python executable."
  exit 1
fi
API_HOST="$("$PYTHON_BIN" -c 'from edge_support.config import Settings; print(Settings.from_env().api_host)')"
API_PORT="$("$PYTHON_BIN" -c 'from edge_support.config import Settings; print(Settings.from_env().api_port)')"
# Fail before launching a dashboard against an unrelated/stale API.
"$PYTHON_BIN" - "$API_HOST" "$API_PORT" <<'PY'
import socket,sys
with socket.socket() as s:
    try: s.bind((sys.argv[1],int(sys.argv[2])))
    except OSError: raise SystemExit('API port already in use; inspect the running service or choose another port.')
PY
API_PID=""
cleanup() { if [[ -n "$API_PID" ]]; then kill "$API_PID" 2>/dev/null || true; fi; }
trap cleanup EXIT INT TERM
"$PYTHON_BIN" -m uvicorn edge_support.api.server:app --host "$API_HOST" --port "$API_PORT" &
API_PID=$!
export EDGE_SUPPORT_API_URL="http://127.0.0.1:$API_PORT"
"$PYTHON_BIN" - <<'PY'
import os,time,httpx
from edge_support.config import Settings
s=Settings.from_env()
headers={'Authorization':'Bearer '+s.action_token} if s.action_token else {}
for _ in range(30):
    try:
        r=httpx.get(os.environ['EDGE_SUPPORT_API_URL']+'/health',headers=headers,timeout=1,trust_env=False)
        if r.status_code==200 and r.json().get('service')=='edgesupport': break
    except (httpx.HTTPError,ValueError): pass
    time.sleep(.3)
else: raise SystemExit('API did not become healthy; inspect its startup error.')
PY
"$PYTHON_BIN" -m streamlit run ui/dashboard.py --server.address 127.0.0.1 --server.port "${EDGE_SUPPORT_UI_PORT:-8501}"
