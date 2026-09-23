import re
from app.models import Decision

SUPPORTED = {"cpu_saturation", "memory_pressure", "thermal_throttling", "disk_pressure",
             "wifi_connectivity", "battery_degradation", "application_crash", "startup", "dns_network"}

def decide(diagnosis, incident, evidence, threshold=.65):
    reasons = []
    if diagnosis.confidence < threshold:
        reasons.append("LOW_CONFIDENCE")
    if diagnosis.issue_category not in SUPPORTED:
        reasons.append("UNSUPPORTED_CATEGORY")
    risk_text = incident.description + " " + incident.logs
    risk_phrase = re.search(r"\b(smoke|burning smell|swollen battery|battery swelling|ransomware|data loss|sparks)\b", risk_text, re.I)
    if incident.high_risk or diagnosis.severity == "high" or risk_phrase:
        reasons.append("HIGH_RISK")
    if diagnosis.insufficient_evidence or not diagnosis.evidence or not evidence:
        reasons.append("INSUFFICIENT_EVIDENCE")
    if incident.troubleshooting_failed:
        reasons.append("TROUBLESHOOTING_FAILED")
    if incident.specialist_requested:
        reasons.append("USER_REQUESTED")
    if diagnosis.needs_escalation:
        reasons.append("MODEL_REQUESTED")
    return Decision(decision="ESCALATE" if reasons else "LOCAL", reason_codes=reasons)
