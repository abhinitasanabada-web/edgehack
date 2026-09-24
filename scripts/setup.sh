#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
if [ ! -f .env ]; then cp .env.example .env; fi
.venv/bin/python scripts/build_index.py
.venv/bin/python scripts/make_dataset.py
printf 'Set LOCAL_LLM_MODEL in .env, then run: bash run_demo.sh   (dashboard :8501, API :8502)
Full Nano test in one session: see docs/NANO_RUNBOOK.md   (bash scripts/run_matrix.sh)
'
