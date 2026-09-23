from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


Severity = Literal["low", "medium", "high", "critical"]


class Diagnosis(BaseModel):
    """The only model output accepted by the application."""

    diagnosis: str = Field(min_length=1, max_length=300)
    evidence: list[str] = Field(min_length=1, max_length=10)
    confidence: float = Field(ge=0.0, le=1.0)
    severity: Severity
    recommended_action: str = Field(min_length=1, max_length=80)
    requires_confirmation: bool = True
    escalate: bool = False
    rationale: str = Field(default="", max_length=500)


class IncidentRequest(BaseModel):
    complaint: str = Field(min_length=1, max_length=4000)
    telemetry: dict = Field(default_factory=dict)


class ActionResult(BaseModel):
    action_id: str
    executed: bool
    success: bool
    message: str
    stdout: str = ""
    stderr: str = ""


class VerificationResult(BaseModel):
    action_id: str
    verified: bool
    message: str
    before: dict = Field(default_factory=dict)
    after: dict = Field(default_factory=dict)

