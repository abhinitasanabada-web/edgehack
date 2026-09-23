# EdgeSupport

EdgeSupport is an edge-first IT support prototype. The ZGX Nano runs the local Qwen model through ZRT, retrieves local runbooks, validates a structured diagnosis, and decides whether an issue can be resolved locally. A Windows endpoint collector gathers telemetry and executes only registry-approved actions. Cloud escalation is disabled by default.

## Architecture

```text
Windows endpoint collector
  -> telemetry JSON -> Nano API :8502
                           |
                           +-- local RAG runbooks
                           +-- local ZRT/vLLM model :8000
                           +-- Pydantic diagnosis validation
                           +-- local/cloud routing decision
                           +-- verification endpoint
  -> Streamlit dashboard :8501
```

The Nano must not execute Windows commands. `windows_collector.ps1` executes the allowlisted action locally on the Windows endpoint after explicit confirmation.

## Nano setup

From the repository root, after ZRT is already serving the model:

```bash
cp .env.example .env
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
chmod +x run_demo.sh
./run_demo.sh
```

Forward port `8501` in VS Code. ZRT remains on `http://127.0.0.1:8000/v1`; the EdgeSupport API uses `8502`; the dashboard uses `8501`.

For a Windows endpoint to reach the Nano API without exposing it publicly, forward port `8502` through VS Code as well. Then the Windows collector can use `http://127.0.0.1:8502` as its `-ApiUrl`.

## Simulation smoke test

For an offline API smoke test, set `SIMULATION_MODE=true` in `.env`, then run `./run_demo.sh`. This mode validates workflow only and is not an AI benchmark. Set `SIMULATION_MODE=false` for the actual Nano model.

## Windows endpoint demo

Run PowerShell on the endpoint laptop, not on the Nano:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\edge_support\collector\windows_collector.ps1 `
  -ApiUrl "http://127.0.0.1:8502" `
  -Complaint "Wi-Fi is connected but websites do not load" `
  -AutoApply `
  -Confirmed
```

Only action IDs in `edge_support/actions/registry.py` can be selected. The script does not accept arbitrary shell commands from the model. Use a private tunnel or approved network path for the endpoint-to-Nano API; do not expose port 8502 publicly.

## Evaluation

Run after the API is available:

```bash
.venv/bin/python eval/evaluate.py --output eval/results.json
```

The starter set contains three cases. Expand it to 100-300 labeled cases before making accuracy, local-resolution, latency, or cloud-avoidance claims. Record p50/p95 latency, diagnosis correctness, action success, verification success, escalation rate, offline behavior, and unsafe-action count.

## Safety and claims

- Cloud is off by default and is never an automatic fallback.
- The model emits an action ID, not a command.
- The action registry and platform checks are mandatory safety boundaries.
- High-risk actions require confirmation.
- Redaction is applied before any future cloud integration; review it before using real logs.
- The included runbooks and incidents are synthetic. They are not official HP support content or an independent benchmark.
