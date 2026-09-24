# Assessment of the proposed site-local routing design

## Fit to the hackathon

The strongest proposed contribution is an auditable escalation policy and an experiment showing its risk/coverage tradeoff. This directly addresses the brief's explicit, defensible, measurable local-versus-escalation decision. A Nano serving a site's laptops is a reasonable deployment scenario. It is not yet a production multi-tenant service: this prototype has one shared incident view, in-memory records and serialized local inference. Site capacity has not been measured.

Raw inputs can be sanitized on the laptop before transmission and again on the Nano. They remain within the site only if the laptop and Nano are actually deployed there and the chosen network path meets that constraint. A remote SSH demonstration does not prove physical data residency. External internet can be unavailable after dependencies/model files are installed, provided the private laptop-to-Nano connection remains available. Do not claim Tailscale establishes an offline connection without testing its actual network/control-plane conditions.

## What is already in the market

Do not claim AI IT diagnosis, telemetry collection, RAG or remediation is new:

- [HP WXP](https://learn.workforceexperience.hp.com/docs/wxp-getting-started-guide) is described by HP as cloud-based device/user-experience management.
- [Nexthink](https://docs.nexthink.com/platform/overview/capabilities) documents telemetry analytics, AI diagnosis, automation and remediation.
- [Microsoft Security Copilot in Intune](https://learn.microsoft.com/en-us/intune/copilot/security-copilot) is cloud-based.
- [HP IQ](https://www.hp.com/us-en/newsroom/press-releases/2026/hp-introduces-hp-iq-connected-ecosystem.html) describes local on-device intelligence and coordination across devices/spaces. Calling it only a single-laptop model understates that positioning.

These sources support cautious product descriptions, not an exhaustive claim that every competitor processes everything in the cloud, operates at a particular fleet size, or lacks tiered routing. We have not established uniqueness, novelty or comparative superiority.

## Agreement and telemetry checks

The integrated implementation samples category/action pairs 3 times by default; `LOCAL_SAMPLE_COUNT=5` enables the proposed five samples. Temperature is nonzero for repeated sampling; five copies of a deterministic response would be weak evidence. Agreement is the winning vote count divided by all requested samples, including invalid outputs. Model confidence remains visible but does not authorize a local result.

Local acceptance additionally requires known category/action IDs, evidence references to supplied sources, compatibility with available telemetry, no malformed samples and no independent high-risk/feedback/specialist gates. One sample is available as a benchmark baseline but always defers because it cannot establish agreement. A threshold sweep compares acceptance coverage with selective error and unsafe acceptance on labeled cases.

Agreement is not correctness, and a valid citation is not semantic entailment. The same model can share the same error across all samples; our telemetry checks cover only known measured categories. The model may still hallucinate explanations or instructions. This is a heuristic needing calibration, not a calibrated confidence probability. [Self-consistency research](https://openreview.net/pdf?id=1PL1NIMMrw) supports studying sample agreement; [research on ambiguity](https://aclanthology.org/2023.blackboxnlp-1.7.pdf) cautions against equating consistency with underlying correctness.

## Local model tiers

The optional ladder is small local -> separately served larger local -> explicit cloud or human support. The second tier is tried only for uncertainty/evidence failures, not physical/security risks, failed remediation or specialist requests. A local server outage never silently invokes cloud. No second model is downloaded, started or claimed to fit automatically. Keep `ENABLE_LARGE_LOCAL=false` until the team has measured available memory, KV cache, context, concurrency and latency on the Nano.

This experiment can reduce cloud requests, but also adds local latency and tokens. Two local models can share errors. The current implementation does not claim that the second tier produces better answers solely because it is named `large`.

## Measurements and energy

Implemented: per-request model/tier/latency and reported token usage, sample agreement, telemetry/citation checks, reason codes, local-only benchmark and threshold sweep CSV/JSON, and a live endpoint collector/dashboard summary. Benchmark failure rows stay in coverage denominators. Unreported usage is null. Transport failures can have unknown billed usage, including earlier requests in a pipeline that aborts: do not derive a complete cost ledger from the current report.

Not yet measured: real integrated-model accuracy, site throughput, Windows action success, large-tier savings, cloud savings or energy. The sweep is a small-tier deferral curve, not a counterfactual multi-tier cost/energy curve. It must not label all deferred incidents as cloud requests because some require human review. The 13 synthetic cases are smoke fixtures, not a sufficient calibration or test set. The 3 teammate fixtures remain as legacy examples.

For a real study, curate independently labeled incidents; split by template/device/root cause into calibration and held-out test sets. Sweep thresholds on calibration only, lock the chosen threshold, then evaluate test outcomes without retuning. Compare sample counts 1, 3 and 5; small-only versus two local tiers; and the original confidence-based router using the same cases and model. Report errors among accepted incidents, coverage, human handoffs, p50/p95 latency, model usage and unresolved cases. No cutoff has been selected from real measurements yet; 0.8 is an illustrative default.

If power telemetry is available, integrate measured power over time in joules (or measure a whole-device wall meter), state the boundary and idle-baseline treatment, and divide by completed incidents. Do not estimate energy from tokens or pretend cloud-provider energy is exposed when it is not.

## Optional distillation

The proposed fine-tuning objective is reasonable: improve a small model's task-category and JSON-format behavior using locally generated teacher labels. This is not automatically reliable supervision: teacher agreement is not ground truth. Review a representative sample with IT expertise and keep an independently labeled test set, separate from teacher-generated training data and retrieval documents. Check source/model licenses and privacy before training.

Measure the small model before/after under identical prompts, hardware and routing policy: category/action accuracy, schema validity, coverage at a fixed risk target, escalation rate, latency and tokens. Include training cost and teacher errors. If it does not improve the target metrics, retain the base model. The pipeline is implemented in `finetune/` (template targets from the train split, optional on-Nano distillation from a second local model); no fine-tuned result is claimed until `scripts/run_matrix.sh finetuned` has been run.

## v2 enhancements (switchable)

Each is an `.env` switch whose default reproduces the original behaviour, so one Nano session can measure it:

- `STRICT_SCHEMA` enumerates category/action IDs and requires evidence at decode time; the router then sees fewer invalid or unsupported outputs. It narrows, not replaces, the validation schema.
- `GATE_MODE=majority` stops a single hedging or malformed sample from vetoing an otherwise unanimous result. Risk, specialist and failed-fix gates stay strict in both modes. Both modes' reasons are computed for every ticket, so the sweep compares them from one model run.
- `RETRIEVAL=bm25` ranks both corpora together with namespaced `kb:` IDs (two file names collided before).
- `LOCAL_REDACTION=keep_network` lets the on-site model see IP addresses (e.g. a 169.254.x.x DHCP failure) while every returned, stored or ticketed field remains fully redacted.
- Calibration is now separated from testing: `evaluate.py --calibrate` on `data/eval/calib.jsonl` chooses the threshold and gate mode (highest coverage with zero unsafe accepts and error <= target) and locks it for `test.jsonl` and the stress set `test_hard.jsonl`.
- The evaluation adds a rules-only baseline, planted-PII leak counts, bytes leaving the site, estimated/measured cloud cost, GPU energy where exposed, per-kind breakdowns and Wilson intervals.
