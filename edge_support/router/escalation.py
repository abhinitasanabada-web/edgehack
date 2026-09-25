"""Deterministic policy. Agreement is a heuristic, never a calibrated probability."""
import re
from collections import Counter
from app.services.privacy import sanitize
from edge_support.actions.registry import get_action
from edge_support.inference.output_schema import CATEGORIES
from app.services.telemetry import CATEGORIES as METRIC_CATEGORIES

HARD_REASONS = {"HIGH_RISK", "USER_REQUESTED", "TROUBLESHOOTING_FAILED", "HIGH_RISK_ACTION"}
UNSAFE_ACTION_REASONS = {"HIGH_RISK_ACTION", "UNKNOWN_ACTION", "ACTION_CATEGORY_MISMATCH"}

def redact(value):
    return sanitize(value)[0]

RISK_PHRASE = r"\b(smoke|burning smell|swollen battery|battery swelling|ransomware|data loss|sparks)\b"
ACTION_CATEGORIES = {"flush_dns":{"dns_network"},"restart_dns_client":{"dns_network"},
                     "close_demo_process":{"cpu_saturation","memory_pressure"},"clear_temp":{"disk_pressure"}}

def _hard(incident, valid):
    reasons = []
    if incident["specialist_requested"]: reasons.append("USER_REQUESTED")
    if incident["troubleshooting_failed"]: reasons.append("TROUBLESHOOTING_FAILED")
    if incident["high_risk"] or re.search(RISK_PHRASE, incident["complaint"]+" "+incident["logs"], re.I) \
            or any(d.severity in {"high","critical"} for d in valid):
        reasons.append("HIGH_RISK")      # strict in every gate mode: one sample seeing danger is enough
    return reasons

def _supported(d, known, relevant, measured):
    cited = set(d.evidence_ids)
    ok = bool(d.evidence and cited and cited <= known)
    # A measured category requires a matching signal citation, not an unrelated runbook.
    return ok and any(s["id"] in cited for s in relevant) if measured else ok

def assess(samples, requested_count, payload, gate_mode="any"):
    """Reasons are computed for BOTH gate modes (reasons_by_mode) so one model run can be swept either way.
    any      (original): a single hedging, weak-evidence, high-risk-action or malformed sample vetoes LOCAL.
    majority           : hedging/insufficient-evidence flags require at least half the valid samples; malformed
                         samples only lower agreement (they already count against it). Any high-risk action or severity vetoes LOCAL."""
    valid = [d for d in samples if d is not None]
    votes_detail = [None if d is None else {"category":d.issue_category,"action":d.recommended_action,
                    "severity":d.severity,"escalate":d.escalate,"insufficient_evidence":d.insufficient_evidence,
                    "evidence_ids":d.evidence_ids} for d in samples]
    incident = payload["incident"]
    if not valid:
        hard = _hard(incident, [])
        reasons = ["INVALID_MODEL_OUTPUT"] + hard
        return {"selected":None,"agreement":0.0,"valid_count":0,"requested_count":requested_count,
                "telemetry_consistent":False,"evidence_supported":False,"base_reasons":reasons,
                "reasons_by_mode":{"any":list(reasons),"majority":list(reasons)},"gate_mode":gate_mode,
                "votes":votes_detail}
    votes = Counter((d.issue_category,d.recommended_action) for d in valid)
    winner, count = votes.most_common(1)[0]
    cluster = [d for d in valid if (d.issue_category,d.recommended_action)==winner]
    known = {s["id"] for s in payload["signals"]} | {"kb:"+k["source"] for k in payload["knowledge"]}
    category = winner[0]
    telemetry = incident["telemetry"]
    observed_metrics = [f for f,c in METRIC_CATEGORIES.items() if c==category and telemetry.get(f) is not None]
    relevant = [s for s in payload["signals"] if s["category"]==category]
    measured = bool(observed_metrics or relevant)
    consistent = not observed_metrics or bool(relevant)
    if category=="dns_network" and (telemetry.get("network") or {}).get("dns_ok") is True:
        consistent = False
    first = cluster[0]
    best = next((d for d in cluster if _supported(d, known, relevant, measured)), first)
    shared = []
    if category not in CATEGORIES: shared.append("UNSUPPORTED_CATEGORY")
    if not get_action(winner[1]): shared.append("UNKNOWN_ACTION")
    if winner[1] in ACTION_CATEGORIES and category not in ACTION_CATEGORIES[winner[1]]:
        shared.append("ACTION_CATEGORY_MISMATCH")
    if not consistent: shared.append("TELEMETRY_CONFLICT")
    risky = lambda d: bool(get_action(d.recommended_action) and get_action(d.recommended_action).high_risk)
    half = lambda flag: sum(1 for d in valid if flag(d)) * 2 >= len(valid)
    hard = _hard(incident, valid)
    any_mode = hard + (["HIGH_RISK_ACTION"] if any(risky(d) for d in valid) else []) + shared
    if any(d.escalate for d in valid) or winner[1]=="no_action_escalate": any_mode.append("MODEL_REQUESTED")
    if any(d.insufficient_evidence for d in valid) or not _supported(first, known, relevant, measured):
        any_mode.append("INSUFFICIENT_EVIDENCE")
    if len(valid)!=requested_count: any_mode.append("INVALID_MODEL_OUTPUT")
    majority = hard + (["HIGH_RISK_ACTION"] if any(risky(d) for d in valid) else []) + shared
    if half(lambda d: d.escalate) or winner[1]=="no_action_escalate": majority.append("MODEL_REQUESTED")
    if half(lambda d: d.insufficient_evidence) or not _supported(best, known, relevant, measured):
        majority.append("INSUFFICIENT_EVIDENCE")
    order = lambda reasons: list(dict.fromkeys(reasons))
    by_mode = {"any":order(any_mode),"majority":order(majority)}
    selected = best if gate_mode=="majority" else first
    return {"selected":selected.model_dump(), "agreement":count/requested_count,"valid_count":len(valid),
            "requested_count":requested_count, "telemetry_consistent":consistent,
            "evidence_supported":_supported(selected, known, relevant, measured),
            "base_reasons":list(by_mode[gate_mode]),"reasons_by_mode":by_mode,"gate_mode":gate_mode,"votes":votes_detail}

def route_assessment(assessment, threshold, gate_mode=None):
    """gate_mode=None uses the mode the assessment was made with; pass "any"/"majority" to re-route offline."""
    by_mode = assessment.get("reasons_by_mode") or {}
    reasons = list(by_mode[gate_mode] if gate_mode in by_mode else assessment["base_reasons"])
    if assessment["requested_count"] < 2:
        reasons.append("INSUFFICIENT_SAMPLES")
    if assessment["agreement"] < threshold: reasons.append("LOW_AGREEMENT")
    reasons = list(dict.fromkeys(reasons))
    abstained = bool(reasons)
    if not abstained:
        abstention = {"active":False, "mode":"none", "reason_codes":[], "message":""}
    elif UNSAFE_ACTION_REASONS.intersection(reasons) or "HIGH_RISK" in reasons:
        abstention = {
            "active":True,
            "mode":"human_review",
            "reason_codes":reasons,
            "message":"No local action was authorized because a safety gate fired; human review is required.",
        }
    else:
        abstention = {
            "active":True,
            "mode":"uncertainty",
            "reason_codes":reasons,
            "message":"No local action was authorized because the system did not have enough trustworthy evidence.",
        }
    return {"decision":"ESCALATE" if abstained else "LOCAL", "reason_codes":reasons,
            "agreement_threshold":threshold,"gate_mode":gate_mode or assessment.get("gate_mode","any"),
            "cloud_called":False,"abstained":abstained,"abstention":abstention}

def decide_route(diagnosis, cloud_enabled=False):
    """Compatibility entry point refuses authorization without measured evidence."""
    reasons = ["MISSING_ROUTING_EVIDENCE"]
    return {"decision":"ESCALATE","reason_codes":reasons,"cloud_called":False,"abstained":True,
            "abstention":{"active":True,"mode":"uncertainty","reason_codes":reasons,
                           "message":"No local action was authorized because routing evidence was missing."}}
