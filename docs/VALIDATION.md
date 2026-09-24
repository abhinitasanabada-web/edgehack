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
