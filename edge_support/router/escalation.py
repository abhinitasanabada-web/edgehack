"""Deterministic policy. Agreement is a heuristic, never a calibrated probability."""
import re
from collections import Counter
from app.services.privacy import sanitize
from edge_support.actions.registry import get_action
from edge_support.inference.output_schema import CATEGORIES
from app.services.telemetry import CATEGORIES as METRIC_CATEGORIES

HARD_REASONS = {"HIGH_RISK", "USER_REQUESTED", "TROUBLESHOOTING_FAILED", "HIGH_RISK_ACTION"}

def redact(value):
    return sanitize(value)[0]

def assess(samples, requested_count, payload):
    valid = [d for d in samples if d is not None]
    if not valid:
        incident=payload['incident']
        hard=[]
        if incident['high_risk'] or re.search(r"\b(smoke|burning smell|swollen battery|ransomware|data loss|sparks)\b",incident['complaint']+' '+incident['logs'],re.I): hard.append('HIGH_RISK')
        if incident['specialist_requested']: hard.append('USER_REQUESTED')
        if incident['troubleshooting_failed']: hard.append('TROUBLESHOOTING_FAILED')
        return {"selected":None,"agreement":0.0,"valid_count":0,"requested_count":requested_count,
                "telemetry_consistent":False,"evidence_supported":False,"base_reasons":["INVALID_MODEL_OUTPUT"]+hard}
    votes = Counter((d.issue_category,d.recommended_action) for d in valid)
    winner, count = votes.most_common(1)[0]
    selected = next(d for d in valid if (d.issue_category,d.recommended_action)==winner)
    known = {s["id"] for s in payload["signals"]} | {"kb:"+k["source"] for k in payload["knowledge"]}
    cited = set(selected.evidence_ids)
    supported = bool(selected.evidence and cited and cited <= known)
    telemetry = payload["incident"]["telemetry"]
    observed_metrics = [f for f,c in METRIC_CATEGORIES.items() if c==selected.issue_category and telemetry.get(f) is not None]
    relevant = [s for s in payload["signals"] if s["category"]==selected.issue_category]
    consistent = not observed_metrics or bool(relevant)
    if selected.issue_category=="dns_network" and (telemetry.get("network") or {}).get("dns_ok") is True:
        consistent = False
    # A measured category requires a matching signal citation, not an unrelated runbook.
    if observed_metrics or relevant:
        supported = supported and any(s["id"] in cited for s in relevant)
    reasons = []
    incident = payload["incident"]
    if incident["specialist_requested"]: reasons.append("USER_REQUESTED")
    if incident["troubleshooting_failed"]: reasons.append("TROUBLESHOOTING_FAILED")
    if incident["high_risk"] or re.search(r"\b(smoke|burning smell|swollen battery|battery swelling|ransomware|data loss|sparks)\b",incident["complaint"]+" "+incident["logs"],re.I) or any(d.severity in {"high","critical"} for d in valid):
        reasons.append("HIGH_RISK")
    if any(get_action(d.recommended_action) and get_action(d.recommended_action).high_risk for d in valid): reasons.append("HIGH_RISK_ACTION")
    if selected.issue_category not in CATEGORIES: reasons.append("UNSUPPORTED_CATEGORY")
    if not get_action(selected.recommended_action): reasons.append("UNKNOWN_ACTION")
    action_categories={"flush_dns":{"dns_network"},"restart_dns_client":{"dns_network"},
                       "close_demo_process":{"cpu_saturation","memory_pressure"},"clear_temp":{"disk_pressure"}}
    if selected.recommended_action in action_categories and selected.issue_category not in action_categories[selected.recommended_action]:
        reasons.append("ACTION_CATEGORY_MISMATCH")
    if any(d.escalate for d in valid) or selected.recommended_action=="no_action_escalate": reasons.append("MODEL_REQUESTED")
    if any(d.insufficient_evidence for d in valid) or not supported: reasons.append("INSUFFICIENT_EVIDENCE")
    if not consistent: reasons.append("TELEMETRY_CONFLICT")
    if len(valid)!=requested_count: reasons.append("INVALID_MODEL_OUTPUT")
    return {"selected":selected.model_dump(), "agreement":count/requested_count,"valid_count":len(valid),
            "requested_count":requested_count, "telemetry_consistent":consistent,"evidence_supported":supported,
            "base_reasons":reasons}

def route_assessment(assessment, threshold):
    reasons = list(assessment["base_reasons"])
    if assessment["requested_count"] < 2:
        reasons.append("INSUFFICIENT_SAMPLES")
    if assessment["agreement"] < threshold: reasons.append("LOW_AGREEMENT")
    return {"decision":"ESCALATE" if reasons else "LOCAL", "reason_codes":list(dict.fromkeys(reasons)),
            "agreement_threshold":threshold,"cloud_called":False}

def decide_route(diagnosis, cloud_enabled=False):
    """Compatibility entry point refuses authorization without measured evidence."""
    return {"decision":"ESCALATE","reason_codes":["MISSING_ROUTING_EVIDENCE"],"cloud_called":False}
