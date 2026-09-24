# Integrated validation record

Local validation on macOS arm64 with Python 3.12.14. Branch: `integrate-edge-routing`. No Nano configuration or running service was changed.

## Executed

- Automated suite: 47 tests (original workflow plus new API, routing, sampling, model adapter, privacy, cloud consent, verification and integrated dashboard).
- A 13-case simulation benchmark completed, with zero cloud requests and explicitly unavailable energy/cost metrics. Its 10/13 category and 11/13 route agreement are fixture outcomes, not model accuracy. JSON/CSV reports are generated under ignored `reports/`.
- The combined launcher started the FastAPI service and Streamlit dashboard on separate temporary loopback ports. Browser submission returned a visible SIMULATION diagnosis, 100% fixture agreement, local route, memory evidence and measured fixture latency. A separate Streamlit AppTest checked the integrated UI.
- Critical/high severity, explicit support requests, failed troubleshooting, risky/unknown/mismatched action IDs, missing evidence, telemetry conflicts, malformed model outputs and low sample agreement defer deterministically.
- Mocked second-tier recovery and second-tier outage exercised; no second model was launched.
- Mocked cloud consent, stored-incident lookup, one-attempt behavior and repeated egress redaction exercised; no real cloud call was made.
- Shell syntax checks passed for startup and setup scripts. Dockerfile/launcher now agree on `.venv`, but this is a code inspection, not a Docker build result.

## Not yet validated

- Integrated real inference on the assigned HP Nano. The user separately showed a Ready Qwen2.5-7B-Instruct service, which does not establish performance of this new integration.
- GPU memory headroom, large-model serving, throughput, sample-budget latency, model agreement/accuracy/calibration, or offline networking conditions on site.
- Docker build/run: Docker CLI exists, but the local daemon socket is unavailable.
- PowerShell syntax/runtime and real Windows actions: PowerShell/Windows runtime unavailable. The collector was reviewed only; use a disposable test endpoint before enabling actions.
- Real endpoint collection-to-Nano flow, cloud accuracy/cost, energy measurement, production authentication/tenant isolation, or distillation.

Tests use synthetic inputs and fake model responses where stated. They establish software behavior; they do not establish diagnostic safety or model quality. Full power/latency/accuracy comparison remains a Nano experiment. The shared latest-incident API is a private demo feature, not a multi-tenant deployment.

## v2 enhancements (branch `enhancements-v2`) — local validation

Validated on macOS arm64, Python 3.13 (Anaconda). No Nano, model server, Windows device or cloud endpoint was available.

Executed:
- Full suite: **73 passed, 4 skipped**. The skips are the API tests that need the real FastAPI (`tests/test_integrated.py` ×2, `tests/test_api_uplink.py` ×2); FastAPI could not be installed here, so those modules were imported through a local stand-in and the API tests skipped. Run `pytest -q` on the Nano to execute them.
- Every original test passes unchanged: all switches default to the pre-v2 behaviour, and with default settings the prompt is byte-identical to before.
- `scripts/make_dataset.py` regenerates train/test byte-identically except for the new `pii` field; calib (78) and test_hard (60) share no phrasing with train.
- `SIMULATE=1 MODE=quick bash scripts/run_matrix.sh` completed end to end (calibrate -> lock -> test + hard for three configs and 1/3/5 samples) and produced the comparison table. Simulation numbers are plumbing checks only.
- The dashboard rendered through Streamlit AppTest for LOCAL and human-handoff results with the new decision panel; the presentation's script ran against a stub DOM with embedded results.
- `finetune/build_sft.py` with STRICT_SCHEMA/COMPACT_PROMPT/RETRIEVAL=bm25: 387/387 targets satisfy the strict schema; it refuses test, calib and hard splits.

Not validated: real-model behaviour of any switch, GB10 latency/throughput/energy, the Windows collector's new battery/Wi-Fi fields (PowerShell unavailable), the `/health` uplink and `/escalate` offline guard under real FastAPI, the fine-tuning container run.

### Independent review of v2 (and fixes)

A second reviewer read the v2 diff for real-service failure modes; no blocker was found. Fixed afterwards:
batched completion tokens were counted n times (vLLM usage already covers all choices); egress/cost now measure
the actual JSON request bodies (system prompt included) for both arms, and cloud escalations send a minimal
redacted payload (payload + diagnosis + route, not per-sample tiers); schema fallbacks are recorded
(`schema_enforced`, `schema_fallback_tickets`); exact threshold fractions (2/3); the action plan uses redacted text;
`run_matrix.sh` pins every switch, runs on bash 3.2, skips calibration for the always-deferring 1-sample
reference, and adds a one-ticket-at-a-time latency probe (matrix rows record `workers`); `run_finetune.sh` passes HF
credentials through a private env file (works with `sudo docker`); `/health` uplink checks run in the background
and only when cloud is enabled. One deliberate default-path difference: when every sample is malformed, the risk
phrase list now also matches "battery swelling" (it already did for valid samples), so such tickets go to a person
without trying the second local tier. Suite after fixes: 79 passed, 4 skipped (FastAPI API tests).
