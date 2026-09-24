# EdgeSupport — project brief

**Team:** _names_ · **Device:** HP ZGX Nano _hpX_ (NVIDIA GB10, 128 GB unified memory) · **Repo:** _URL_ · **Video:** _URL_

## Target user and problem
A Tier-1 IT help-desk technician supporting employees at a site with many laptops, such as a hospital, school
district or factory. Most tickets are recurring device problems: CPU or memory pressure, a full disk, heat,
battery wear, Wi-Fi, DNS, crashing apps, slow boots. Diagnosing them means reading telemetry and logs that contain
e-mails, user paths and internal IPs, which site policy keeps on premises. The most common ticket ("websites won't
load") is also exactly when a cloud assistant can't be reached.

## Solution
EdgeSupport runs on the site's ZGX Nano.
- A laptop collector sends CPU, memory, disk, battery, Wi-Fi and DNS readings.
- Secrets, e-mails and user paths are redacted, readings become threshold signals, and BM25 retrieves runbooks.
- A local Qwen model served by HP ZRT (vLLM) answers 3–5 times in one batched request, under an enforced output
  schema.
- A ticket stays **local** only if the answers agree, cite an existing signal or runbook, telemetry agrees, and no
  safety gate fires. Risk phrases, high severity, specialist requests and failed fixes always go to a person.
- The agreement threshold and gate mode are chosen on a calibration split and locked before testing.
- The cloud is an optional second opinion that needs a person's approval and never authorizes a fix.
- On Windows, two allowlisted fixes (flush DNS, gracefully close a demo app) run only after a LOCAL route and a typed
  `APPLY`, then are verified before and after.

## Why the cloud alone can't do this
- **Data residency.** Raw telemetry stays on site. Planted identifiers leaked into outputs: _0/N_.
- **Connectivity.** Diagnosis needs only the Nano; with the uplink cut, answers continue and escalations stay local.
- **Latency.** Median _N_ s per ticket on the Nano.
- **Cost.** Only deferred tickets can reach the cloud, and only on approval: _H_ bytes per ticket vs _C_ cloud-only.

## Evidence (held-out synthetic tickets; see reports/base/summary.md)
- Share answered on site, and the error among those.
- Unsafe accepts (target 0).
- Category accuracy with a 95% interval, against a rules-only baseline.
- Results on the stress set (misleading complaints, distractor readings, just-below-threshold values).
- A/B of each enhancement.
- 1/3/5 samples.
- Fine-tuned vs base, if run.

## Built with
HP ZGX Nano (GB10) · HP ZTK · HP ZRT (vLLM) · Qwen2.5-7B-Instruct · FastAPI · Streamlit · original synthetic
runbooks and benchmark.
