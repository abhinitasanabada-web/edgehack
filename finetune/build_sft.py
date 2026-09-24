"""Build the fine-tuning set for the integrated pipeline from the TRAIN split only (never test).

Why: the router only keeps a ticket local when samples agree on category AND action and cite
exact evidence IDs (signal:<field>, kb:<file>). A stock 7B model often drifts on those details.
Each target below is a "perfect answer" in the integrated Diagnosis schema, built from the
gold label and the SAME payload the app sends (edge_support.services.pipeline.prepare), with
the SAME prompt (edge_support.inference.model_client.messages).

Target sources:
  (default)        templated from gold labels: consistent category/action/evidence-ID format
  --teacher large  on-Nano distillation: the served large model answers; kept only when its
                   category and action match the gold label, otherwise the template is used
Output: finetune/data/sft.jsonl in TRL prompt/completion format (loss on the answer only), plus
finetune/data/sft_meta.json recording the prompt-affecting switches. Build it AFTER choosing the .env
switches (STRICT_SCHEMA, COMPACT_PROMPT, RETRIEVAL, LOCAL_REDACTION): the model must be trained on the
exact prompt it will see at inference.
"""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from edge_support.config import Settings, ROOT
from edge_support.inference.output_schema import Diagnosis, IncidentRequest
from edge_support.inference.model_client import LocalModelClient, ModelError, messages
from edge_support.services.pipeline import prepare
from app.services.retrieval import build_index

# Knowledge files (original corpus + teammate runbooks) that support each category, best first.
KB = {"cpu_saturation": ["cpu_saturation.md", "startup_overload.md"],
      "memory_pressure": ["high_memory.md", "memory_pressure.md"],
      "disk_pressure": ["disk_full.md", "disk_pressure.md"],
      "thermal_throttling": ["thermal_throttling.md"],
      "battery_degradation": ["battery_degradation.md"],
      "wifi_connectivity": ["wifi_failure.md", "wifi_connectivity.md", "network_failure.md"],
      "dns_network": ["dns_failure.md", "dns_network.md"],
      "application_crash": ["application_crash.md"],
      "startup": ["startup_overload.md", "startup.md"]}

CAUSE = {"cpu_saturation": "Sustained high CPU load from a running application is slowing the device.",
         "memory_pressure": "Memory is nearly exhausted, causing paging, freezes and slow applications.",
         "disk_pressure": "The system drive is nearly full, which blocks updates and saving files.",
         "thermal_throttling": "The device is running hot and likely throttling performance.",
         "battery_degradation": "Battery capacity has degraded, shortening runtime.",
         "wifi_connectivity": "A weak or unstable Wi-Fi signal is causing intermittent connectivity.",
         "dns_network": "The network is connected but hostname resolution (DNS) is failing.",
         "application_crash": "A specific application is crashing repeatedly.",
         "startup": "Startup is slow, likely due to many programs launching at login."}

STEPS = {"cpu_saturation": ["Save your work.", "Open Task Manager and identify the busiest process.", "Close unneeded applications normally."],
         "memory_pressure": ["Save your work.", "Close unused applications and browser tabs.", "Restart the device after saving if memory stays high."],
         "disk_pressure": ["Review storage usage in Settings.", "Remove only files you own and have backed up.", "Ask IT before deleting anything unfamiliar."],
         "thermal_throttling": ["Place the device on a hard, ventilated surface.", "Reduce workload and check vents without opening the device.", "Stop using it and contact IT if you notice smoke, a burning smell or swelling."],
         "battery_degradation": ["Check the manufacturer battery report.", "Use approved chargers.", "Request a battery replacement through IT if capacity is low."],
         "wifi_connectivity": ["Move closer to the access point.", "Reconnect to the approved network.", "Compare with another device on the same network."],
         "dns_network": ["Confirm other sites or services work.", "Flush the DNS cache after confirmation.", "Check VPN status and report the exact error if it persists."],
         "application_crash": ["Record the application name, error and time.", "Install approved updates for the application.", "Report repeated crashes to IT with the redacted log."],
         "startup": ["Disable nonessential startup apps in Task Manager.", "Disconnect unneeded peripherals.", "Avoid repeated forced shutdowns."]}

def incident(case):
    data = dict(case["incident"])
    data["complaint"] = data.pop("description")
    return IncidentRequest.model_validate(data)

def template_target(case, payload):
    category, action, kind = case["expected_category"], case["expected_action"], case.get("kind", "")
    inc = case["incident"]
    risky = kind == "risk_phrase" or inc.get("high_risk")
    if category == "unsupported":
        return Diagnosis(issue_category="unsupported", diagnosis="This request is outside supported PC troubleshooting.",
                         confidence=.2, severity="low", recommended_action="no_action_escalate",
                         recommended_steps=["Route the request to the appropriate team."], escalate=True,
                         insufficient_evidence=True, rationale="No supported category matches the complaint or telemetry.")
    signal_ids = [s["id"] for s in payload["signals"] if s["category"] == category]
    # Match by file name so this works for bare (legacy) and namespaced (bm25: "runbooks/x.md") sources.
    sources = [k["source"] for k in payload["knowledge"]]
    kb_ids = ["kb:" + src for f in KB.get(category, []) for src in sources if Path(src).name == f][:1]
    evidence_ids = signal_ids + kb_ids
    evidence = [f"{s['field']}={s['value']}" for s in payload["signals"] if s["category"] == category]
    evidence += [f"Runbook {Path(k[3:]).name}" for k in kb_ids]
    if inc.get("logs"):
        evidence.append("Log: " + inc["logs"][:120])
    if risky:
        return Diagnosis(issue_category=category, diagnosis="Possible physical, security or data-loss risk. Stop using the device and contact IT.",
                         evidence=evidence or ["Reported risk in the complaint"], evidence_ids=evidence_ids, confidence=.6,
                         severity="high", recommended_action="no_action_escalate",
                         recommended_steps=["Stop using the device.", "Contact IT support immediately."],
                         escalate=True, rationale="Risk conditions always require human support.")
    return Diagnosis(issue_category=category, diagnosis=CAUSE[category], evidence=evidence, evidence_ids=evidence_ids,
                     confidence=.9 if signal_ids else .75, severity="medium", recommended_action=action,
                     recommended_steps=STEPS[category], insufficient_evidence=not evidence_ids,
                     rationale="Telemetry and runbook agree." if signal_ids else "Complaint matches the runbook; no telemetry supplied.")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--teacher", choices=["large", "small"])
    ap.add_argument("--split", default=str(ROOT / "data/eval/train.jsonl"))
    ap.add_argument("--output", default=str(ROOT / "finetune/data/sft.jsonl"))
    args = ap.parse_args()
    if any(tag in Path(args.split).name for tag in ("test", "calib", "hard")):
        sys.exit("Refusing to train on a scoring split (test/test_hard/calib).")
    settings = Settings.from_env()
    build_index()
    teacher = LocalModelClient(settings) if args.teacher else None
    rows, rejected = [], 0
    for case in map(json.loads, Path(args.split).read_text().splitlines()):
        payload, _ = prepare(incident(case), settings)
        target = None
        if teacher:
            try:
                answer, _ = teacher.sample(payload, args.teacher, 0)
                ok = answer and answer.issue_category == case["expected_category"] and answer.recommended_action == case["expected_action"]
                target = answer if ok else None
            except ModelError:
                target = None
            rejected += target is None
        target = target or template_target(case, payload)
        # Same prompt as inference: the schema is enforced in batched mode, and in sequential mode with STRICT_SCHEMA.
        rows.append({"id": case["id"], "prompt": messages(payload, settings, settings.batch_samples or settings.strict_schema),
                     "completion": [{"role": "assistant", "content": target.model_dump_json()}]})
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r) + "\n" for r in rows))
    switches = {k: getattr(settings, k) for k in ("strict_schema", "compact_prompt", "retrieval", "local_redaction", "batch_samples")}
    system = rows[0]["prompt"][0]["content"] if rows else ""
    meta = {"examples": len(rows), "split": Path(args.split).name, "teacher": args.teacher, "switches": switches,
            "system_prompt_sha256": hashlib.sha256(system.encode()).hexdigest(),
            "created": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    out.with_name("sft_meta.json").write_text(json.dumps(meta, indent=2))
    print(f"{len(rows)} examples -> {out}" + (f" ({rejected} teacher answers rejected, template used)" if teacher else ""))
    print(f"prompt switches baked into this data: {switches}  (serve the tuned model with the SAME .env switches)")

if __name__ == "__main__":
    main()
