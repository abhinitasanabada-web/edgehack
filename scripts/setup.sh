#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
if [ ! -f .env ]; then cp .env.example .env; fi
.venv/bin/python scripts/build_index.py
.venv/bin/python scripts/make_dataset.py
printf 'Set LOCAL_LLM_MODEL in .env, then run: .venv/bin/python -m streamlit run app/ui.py
'
