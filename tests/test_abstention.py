from edge_support.config import Settings
from edge_support.inference.output_schema import Diagnosis, IncidentRequest
from edge_support.router.escalation import assess, route_assessment
from edge_support.services.pipeline import diagnose


def payload():
    return {
        "incident": {
            "complaint": "Apps freeze",
            "telemetry": {"memory_percent": 94},
            "logs": "",
            "high_risk": False,
            "specialist_requested": False,
            "troubleshooting_failed": False,
        },
        "signals": [{"id": "signal:memory_percent", "category": "memory_pressure",
                     "field": "memory_percent", "value": 94}],
        "knowledge": [],
    }


def diagnosis(**updates):
    value = {
        "issue_category": "memory_pressure",
        "diagnosis": "High memory use",
        "evidence": ["memory_percent is 94"],
        "evidence_ids": ["signal:memory_percent"],
        "confidence": .9,
        "severity": "medium",
        "recommended_action": "collect_more_telemetry",
    }
    value.update(updates)
    return Diagnosis(**value)


class Fake:
    def __init__(self, values):
        self.values = values

    def sample(self, payload, tier="small", sample_index=0):
        value = self.values[sample_index]
        return value, {"tier": tier, "model": "fixture", "latency_ms": 1, "valid": bool(value)}


def test_router_exposes_explicit_abstention_for_disagreement():
    d = diagnosis()
    other = diagnosis(issue_category="cpu_saturation")
    assessment = assess([d, other, d], 3, payload())
    route = route_assessment(assessment, .8)
    assert route["decision"] == "ESCALATE"
    assert route["abstained"] is True
    assert route["abstention"]["active"] is True
    assert route["abstention"]["mode"] == "uncertainty"
    assert "LOW_AGREEMENT" in route["abstention"]["reason_codes"]


def test_safe_local_result_is_not_abstained():
    request = IncidentRequest(complaint="Apps freeze", telemetry={"memory_percent": 94})
    result = diagnose(request, Settings(), Fake([diagnosis()] * 3))
    assert result["route"]["abstained"] is False
    assert result["abstention"]["active"] is False
    assert result["metrics"]["unsafe_action_blocked"] is False
    assert result["action_plan"]["status"] == "AUTHORIZED_PENDING_CONFIRMATION"


def test_risky_action_is_abstained_and_blocked():
    request = IncidentRequest(complaint="Apps freeze", telemetry={"memory_percent": 94})
    risky = diagnosis(recommended_action="clear_temp")
    result = diagnose(request, Settings(), Fake([risky] * 3))
    assert result["route"]["abstained"] is True
    assert result["action_plan"]["allowed"] is False
    assert result["action_plan"]["status"] == "BLOCKED_BY_POLICY"
    assert result["metrics"]["unsafe_action_proposed"] is True
    assert result["metrics"]["unsafe_action_blocked"] is True
    assert "HIGH_RISK_ACTION" in result["action_plan"]["block_reasons"]


def test_invalid_model_output_abstains_without_authorizing_action():
    request = IncidentRequest(complaint="Something is wrong", telemetry={})
    result = diagnose(request, Settings(), Fake([None, None, None]))
    assert result["route"]["abstained"] is True
    assert result["route"]["abstention"]["mode"] == "uncertainty"
    assert result["action_plan"]["allowed"] is False
    assert result["metrics"]["unsafe_action_blocked"] is False

