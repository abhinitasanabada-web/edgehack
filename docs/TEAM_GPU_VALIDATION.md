# Combined-branch GPU validation — 2026-09-24

All seven pre-existing remote branches are ancestors of `integrate-team-gpu`:
`main`, `edgesupport-product`, `integrate-edge-routing`, `claude/amazing-newton-tlmdjk`,
`enhancements-v2`, `fix-enhancement-validation`, and `abstention-system`.
Git ancestry retained shared commits once; no duplicate cherry-picks or file copying between branches.
The original app remains as a documented legacy entry point. Use `bash run_demo.sh` for the combined app.

## What ran

- 107 automated tests passed on macOS Python 3.12.14 and Nano Python 3.12.3; none skipped.
  Includes real FastAPI TestClient and Streamlit AppTest. One upstream deprecation warning remains.
- Full quick simulation matrix: baseline/schema/full settings, 1/3/5 samples, calibration locks,
  normal/hard scoring, report comparison and single-ticket latency probe. Simulation is not model accuracy.
- NVIDIA GB10 with the already-running `hf:Qwen/Qwen2.5-7B-Instruct` server on port 8000.
  Five initial smoke cases plus 100 baseline/enhanced calibration and evaluation cases completed.
  Each configuration used the first 10 calibration, first 20 test and first 20 hard-test cases.
  Three samples per ticket, four concurrent tickets. No cloud requests, schema fallback, truncated
  responses or invalid samples in the held-out comparison.
- Final-code launcher check started FastAPI and Streamlit on temporary loopback ports, made two
  real GPU diagnoses, and verified `/health`, `/latest`, `/verify`, cloud-disabled rejection,
  redacted email/IP/token output and high-risk abstention. Test services were stopped afterward.
  `FORCE_OFFLINE` exercised the offline demo setting; the physical network was not disconnected.
- Real Linux telemetry collection on the Nano passed the incident input schema. No endpoint actions ran.
- All 387 generated training targets passed strict-schema validation. No weights were trained or uploaded.
- Python compilation, shell syntax checks and `git diff --check` passed.

The benchmark ran at `aee4f10`; the final automated and live API checks ran at `95016a3`.
The intervening fixes preserve boolean safety flags and carry abstention/defer-all metrics into reports.
The strict-schema benchmark emitted valid boolean values; no schema fallback occurred.

## Measured results and limits

[Generated comparison](../reports/gpu-integration/summary.md) and
[machine-readable summary](../reports/gpu-integration/summary.json) contain measured results,
confidence intervals, tokens and sampled GPU-board energy. Thresholds were selected only on calibration
and then locked; the test results were not used to retune them.

Baseline category accuracy was 95% (normal) / 90% (hard), with 0% accepted locally.
Enhanced accuracy was 85% / 85%, with 15% / 5% accepted locally. Median latency was about 14.9 s
versus 10.3 s with four tickets in flight. No accepted case was labelled must-escalate; the enhanced
run accepted only four of its 40 held-out cases. Zero observed errors among those four is weak evidence,
not a safety guarantee. Some ordinary tickets were deferred because the model reported high severity.

Four planted identifiers per normal-test run were checked, with zero leaks; the selected hard subset
had none. Separate API checks also exercised planted email/IP/token redaction. Pattern redaction is
not a guarantee of removing arbitrary personal or proprietary information.

Cloud was disabled. Payload-byte and cloud-cost comparisons are hypothetical/estimated, not observed
internet traffic or measured provider bills. GPU energy excludes CPU/system power and idle subtraction.
There is no claim of statistically established accuracy improvement, production readiness, full-dataset
validation, Windows action execution, a second local model, cloud inference or GPU LoRA training.

## Reproduce on the Nano

Use a new checkout to preserve the existing `~/edgehack` uncommitted work. The prepared independent
checkout is `~/edgehack-integrated-20260924`; it reuses the existing `.venv` without installing packages.
For a fresh machine, clone `main` into a new directory and run `bash scripts/setup.sh`.

```bash
cd ~/edgehack-integrated-20260924
.venv/bin/python -m pytest -q
EDGE_SUPPORT_UI_PORT=18601 bash run_demo.sh
```

The prepared `.env` uses the served Qwen model, cloud disabled, enhanced switches, and the calibrated
`GATE_MODE=any`, `AGREEMENT_THRESHOLD=1.0`, with API port 18602. The command above sets dashboard port 18601.
Forward port **18601** in VS Code and open its forwarded address. The model must remain available on
Nano loopback port 8000. The launcher does not start or stop the model server.

To reproduce the broader comparison, use `MODE=quick bash scripts/run_matrix.sh quick` (30 cases per split),
or `bash scripts/run_matrix.sh base` for the full datasets. These are larger than this bounded validation.
Keep calibration/test splits separate and do not select a new threshold based on test results.


## Follow-up: GPU training smoke tests (2026-09-25)

After the integration checks above, two bounded GPU LoRA tests passed training, evaluation, merging and saving. The original model was restored and answered a real inference request afterward. This supersedes the earlier “no GPU training” status only for those short tests; full training and quality improvement remain unvalidated. See the [manual guide](../finetune/README.md) and [measured memory report](../reports/training-oom-probe/summary.md).
