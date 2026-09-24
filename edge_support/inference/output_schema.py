import json
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.models import Telemetry

CATEGORIES = {"cpu_saturation", "memory_pressure", "thermal_throttling", "disk_pressure",
              "wifi_connectivity", "battery_degradation", "application_crash", "startup", "dns_network"}

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

class Diagnosis(StrictModel):
    issue_category: str = Field(default="unsupported", min_length=1, max_length=80)
    diagnosis: str = Field(min_length=1, max_length=1000)
    evidence: list[str] = Field(default_factory=list, max_length=10)
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)
    confidence: float = Field(ge=0, le=1)
    severity: Literal["low", "medium", "high", "critical"]
    recommended_action: str = Field(min_length=1, max_length=80)
    recommended_steps: list[str] = Field(default_factory=list, max_length=10)
    requires_confirmation: bool = True
    escalate: bool = False
    insufficient_evidence: bool = False
    rationale: str = Field(default="", max_length=1000)

class IncidentRequest(StrictModel):
    complaint: str = Field(min_length=5, max_length=6000)
    telemetry: dict = Field(default_factory=dict)
    logs: str = Field(default="", max_length=20000)
    troubleshooting_failed: bool = False
    specialist_requested: bool = False
    high_risk: bool = False

    @field_validator("telemetry")
    @classmethod
    def validate_telemetry(cls, value):
        if len(json.dumps(value, allow_nan=False).encode()) > 30000:
            raise ValueError("Telemetry exceeds 30 KB")
        metrics = {key: value[key] for key in Telemetry.model_fields if key in value}
        Telemetry.model_validate(metrics)
        network = value.get("network")
        if network is not None:
            if not isinstance(network, dict) or (network.get("dns_ok") is not None and type(network["dns_ok"]) is not bool):
                raise ValueError("network.dns_ok must be boolean or null")
        processes = value.get("processes", [])
        if not isinstance(processes, list) or len(processes)>100 or any(not isinstance(p,dict) for p in processes):
            raise ValueError("processes must be a list of at most 100 objects")
        return value

class ActionResult(StrictModel):
    action_id: str
    executed: bool
    success: bool
    message: str
    stdout: str = ""
    stderr: str = ""

class VerificationResult(StrictModel):
    action_id: str
    verified: bool
    message: str
    before: dict = Field(default_factory=dict)
    after: dict = Field(default_factory=dict)

class VerificationRequest(StrictModel):
    action_id: str
    before: dict
    after: dict
    target_process: str | None = None
    action_success: bool = False

class EscalationRequest(StrictModel):
    incident_id: str
    consent: bool = False
