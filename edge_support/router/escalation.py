from __future__ import annotations

import re

from edge_support.actions.registry import get_action
from edge_support.inference.output_schema import Diagnosis


def redact(value: object) -> object:
    if isinstance(value, dict):
        return {str(k): redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if not isinstance(value, str):
        return value
    value = re.sub(r"[\w.+-]+@[\w.-]+", "[REDACTED_EMAIL]", value)
    value = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "[REDACTED_IP]", value)
    return re.sub(r"(?i)(?:C:\\Users\\|/home/)[^\s]+", "[REDACTED_PATH]", value)


def decide_route(diagnosis: Diagnosis, cloud_enabled: bool) -> dict:
    action = get_action(diagnosis.recommended_action)
    safe_local = bool(action and not action.high_risk and diagnosis.confidence >= 0.75 and not diagnosis.escalate)
    if safe_local:
        return {"decision": "LOCAL", "reason": "Known issue, high confidence and registered safe action", "cloud_called": False}
    if not cloud_enabled:
        return {"decision": "LOCAL_ONLY_ESCALATION", "reason": "Cloud disabled; retain a local escalation package", "cloud_called": False}
    return {"decision": "ESCALATE", "reason": "Low confidence, unfamiliar issue or higher-risk action", "cloud_called": False}

