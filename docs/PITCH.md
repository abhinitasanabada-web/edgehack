# Pitch (3 minutes) + Q&A prep

The brief asks for one visual each of: **AI system architecture**, **benchmarks/evidence** and **impact**. The deck
(`docs/presentation/index.html`, results embedded by `scripts/build_deck.py`) has all three, and it is interactive,
as the brief asks. Fill the blanks (_X_) from `reports/base/summary.md`.

## Script

**Problem (30 s).** "Picture a Tier-1 help-desk technician at a site with hundreds of laptops. Most tickets are the
same dozen problems, but diagnosing each one means reading telemetry and logs full of e-mails, user paths and
internal IPs, data that shouldn't leave the building. And the most common ticket, 'websites won't load', is
exactly when a cloud assistant is unreachable."

**Solution (60 s).** *Architecture slide, play "Routine ticket".* "EdgeSupport runs on the ZGX Nano at the site. A
collector sends the laptop's readings. We strip secrets and e-mails, turn readings into signals, and retrieve our
runbooks with BM25. A Qwen model served by ZRT answers three times in one batched request, with the output schema
enforced. Then comes the explicit decision the brief asks for. Risk, a specialist request or a failed fix always
goes to a person. Otherwise the ticket stays local only if the answers agree, cite a real signal and runbook, and
the telemetry agrees. The threshold is locked on a separate calibration split. The cloud is a second opinion that
needs a person's approval, and it can never authorize a fix."

**Result (45 s).** *Evidence slide.* "On _151_ held-out tickets: _X_% answered on site, _Y_% error among those, _0_
unsafe accepts. The strict schema and better retrieval alone moved on-site answers from _A_% to _B_% with no
training. We planted _N_ identifiers in the tickets; _0_ leaked into any output. A redacted ticket is _H_ bytes,
against _C_ for a cloud-only design, and it is only sent on approval."

**Impact (30 s).** *Impact slide, sliders live.* "A 3,000-person site: about _T_ tickets a year answered in seconds
on site, telemetry that never leaves, and it keeps working when the uplink doesn't."

**Close (15 s).** "Diagnose on site. Escalate with evidence."

## Q&A

| Question | Answer |
|---|---|
| *How is the escalation decision measurable?* | Every ticket carries reason codes. We sweep the agreement threshold for both gate modes and plot coverage against error, then lock the operating point on a calibration split before scoring test. The slider is that curve. |
| *Why an LLM, if thresholds catch most of it?* | We measured it. The rules-only baseline (thresholds + keywords) scores _R_% overall, but drops on text-only and log-only tickets, where nothing numeric fires. The by-type chart shows exactly where the model earns its place. It also cites evidence and writes the steps. |
| *Isn't self-agreement weak evidence?* | Alone, yes, and it's uncalibrated. That's why local answers also need a cited signal or runbook, telemetry that agrees, and every safety gate passed. The hard set includes misleading complaints and just-below-threshold readings to test exactly this. |
| *What does "majority" gate mode change?* | Originally one hedging or malformed sample vetoed an otherwise unanimous answer. Majority mode makes uncertainty need half the samples. Risk gates stay strict in both. Calibration picks whichever gives more on-site answers at zero unsafe accepts. |
| *Synthetic data?* | Yes, team-written and said plainly. Train, calibration, test and hard splits use disjoint phrasings, so the fine-tuned model never saw a test sentence. The claim is about the routing behaviour and the relative gains, not field accuracy. |
| *What leaves the building?* | Nothing unless a person approves a cloud second opinion. Then only the redacted ticket, and the dashboard shows exactly those bytes. The on-site model may see IPs (they're evidence, e.g. 169.254.x.x); outputs never contain them. |
| *What did you learn on GB10?* | Batching all samples into one request (vLLM `n`) plus concurrent tickets is the throughput lever. Fill in latency, sample-count and fine-tuning effects from the "What we learned" slide. |
| *Could this remediate automatically?* | Only on the Windows endpoint, only from a two-item allowlist, only after a LOCAL route, and only after a person types APPLY. It then verifies before/after. The Nano never executes commands. |
