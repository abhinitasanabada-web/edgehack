from __future__ import annotations

from fastapi import FastAPI, HTTPException

from edge_support.actions.verifier import verify
from edge_support.config import Settings
from edge_support.inference.model_client import LocalModelClient
from edge_support.inference.output_schema import IncidentRequest
from edge_support.rag.retriever import retrieve
from edge_support.router.escalation import decide_route, redact

app = FastAPI(title="EdgeSupport API", version="0.1.0")


def _simulation_diagnosis(complaint: str, telemetry: dict):
    from edge_support.inference.output_schema import Diagnosis

    text = complaint.lower()
    if "dns" in text or telemetry.get("network", {}).get("dns_ok") is False:
        return Diagnosis(diagnosis="DNS resolution failure", evidence=["DNS lookup failed"], confidence=0.94, severity="medium", recommended_action="flush_dns", requires_confirmation=True, rationale="The endpoint reports failed DNS resolution.")
    if telemetry.get("memory_percent", 0) >= 90 or "memory" in text or "slow" in text:
        return Diagnosis(diagnosis="High memory pressure", evidence=["Memory utilization is high"], confidence=0.88, severity="medium", recommended_action="close_demo_process", requires_confirmation=True, rationale="Memory pressure is consistent with a large running process.")
    return Diagnosis(diagnosis="Unfamiliar or ambiguous endpoint issue", evidence=["Insufficient matching telemetry"], confidence=0.42, severity="medium", recommended_action="no_action_escalate", requires_confirmation=False, escalate=True, rationale="More evidence is required before changing the endpoint.")


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "edgesupport", "cloud_enabled": Settings.from_env().enable_cloud}


@app.post("/diagnose")
def diagnose(request: IncidentRequest) -> dict:
    settings = Settings.from_env()
    knowledge = retrieve(request.complaint + " " + str(request.telemetry))
    try:
        diagnosis = _simulation_diagnosis(request.complaint, request.telemetry) if settings.simulation_mode else LocalModelClient(settings).diagnose(request.complaint, request.telemetry, knowledge)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Local inference failed: {exc}") from exc
    return {"diagnosis": diagnosis.model_dump(), "route": decide_route(diagnosis, settings.enable_cloud), "knowledge": [{"source": x["source"], "score": x["score"]} for x in knowledge]}


@app.post("/verify")
def verification(request: dict) -> dict:
    if not all(key in request for key in ("action_id", "before", "after")):
        raise HTTPException(status_code=400, detail="action_id, before and after are required")
    return verify(request["action_id"], request["before"], request["after"]).model_dump()


@app.post("/redact")
def redaction(payload: dict) -> dict:
    return {"redacted": redact(payload)}

