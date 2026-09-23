#!/usr/bin/env bash
set -euo pipefail

export PYTHONPATH="${PYTHONPATH:-}:$(pwd)"
API_PID=""
cleanup() { if [[ -n "$API_PID" ]]; then kill "$API_PID" 2>/dev/null || true; fi; }
trap cleanup EXIT INT TERM

if [[ ! -x .venv/bin/python ]]; then
  echo "Create the environment first: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi

.venv/bin/python -m uvicorn edge_support.api.server:app --host "${EDGE_SUPPORT_API_HOST:-127.0.0.1}" --port "${EDGE_SUPPORT_API_PORT:-8502}" &
API_PID=$!
sleep 2
.venv/bin/python -m streamlit run ui/dashboard.py --server.address 127.0.0.1 --server.port 8501

