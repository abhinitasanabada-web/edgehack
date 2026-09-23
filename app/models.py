from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

class Process(StrictModel):
    name: str = Field(max_length=200)
    cpu_percent: float = Field(ge=0, le=100)

class Telemetry(StrictModel):
    cpu_percent: float | None = Field(default=None, ge=0, le=100)
    memory_percent: float | None = Field(default=None, ge=0, le=100)
    disk_percent: float | None = Field(default=None, ge=0, le=100)
    temperature_c: float | None = Field(default=None, ge=-30, le=150)
    battery_health_percent: float | None = Field(default=None, ge=0, le=100)
    wifi_signal_percent: float | None = Field(default=None, ge=0, le=100)
    top_processes: list[Process] = Field(default_factory=list, max_length=50)

class Incident(StrictModel):
    description: str = Field(min_length=5, max_length=6000)
    telemetry: Telemetry = Field(default_factory=Telemetry)
    logs: str = Field(default="", max_length=20000)
    troubleshooting_failed: bool = False
    specialist_requested: bool = False
    high_risk: bool = False

class Diagnosis(StrictModel):
    issue_category: str = Field(min_length=1, max_length=100)
    likely_cause: str = Field(min_length=1, max_length=2000)
    confidence: float = Field(ge=0, le=1)
    severity: Literal["low", "medium", "high"]
    evidence: list[str] = Field(max_length=20)
    recommended_actions: list[str] = Field(min_length=1, max_length=10)
    needs_escalation: bool
    escalation_reason: str | None
    insufficient_evidence: bool = False

class Decision(StrictModel):
    decision: Literal["LOCAL", "ESCALATE"]
    reason_codes: list[str]
