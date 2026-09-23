import json
import time
from app.models import Incident
from app.services.privacy import sanitize
from app.services.telemetry import analyze
from app.services.retrieval import retrieve
from app.services.provider import LocalProvider, SimulationProvider, ProviderError
from app.services.escalation import decide


def run(incident, settings, provider=None):
    start = time.perf_counter()
    clean, counts = sanitize(incident.model_dump())
    safe = Incident.model_validate(clean)
    signals = analyze(safe.telemetry, settings.thresholds)
    hits = retrieve(safe.description + " " + safe.logs + " " + " ".join(s["category"] for s in signals))
    payload = {"incident": clean, "signals": signals, "knowledge": hits}
    # Knowledge may itself contain identifiers; sanitize all material entering the model.
    payload, more = sanitize(payload)
    for key,n in more.items():
        counts[key] = counts.get(key, 0) + n
    provider = provider or (SimulationProvider() if settings.simulation else LocalProvider(settings))
    inference_start = time.perf_counter()
    diagnosis = provider.diagnose(payload)
    inference_ms = (time.perf_counter() - inference_start)*1000
    decision = decide(diagnosis, safe, signals or hits, settings.confidence_threshold)
    ticket, output_counts = sanitize({"payload": payload, "diagnosis": diagnosis.model_dump(), "decision": decision.model_dump()})
    for key,n in output_counts.items():
        counts[key] = counts.get(key, 0) + n
    return {"diagnosis": ticket["diagnosis"], "decision": decision.model_dump(),
            "signals": signals, "retrieved": ticket["payload"]["knowledge"], "redactions": counts,
            "latency_ms": round((time.perf_counter()-start)*1000, 2), "inference_ms": round(inference_ms,2),
            "processing_location": "SIMULATION" if settings.simulation else "LOCAL",
            "cloud_sent": False, "cloud_status": "Not requested", "ticket": ticket}


def escalate(result, settings, consent=False, provider=None):
    if settings.simulation:
        raise ProviderError("Cloud calls are unavailable in simulation mode.")
    if result["decision"]["decision"] != "ESCALATE":
        raise ProviderError("Cloud processing requires an escalation decision.")
    if not settings.enable_cloud:
        raise ProviderError("Human/cloud escalation recommended, but cloud processing is disabled.")
    if not consent:
        raise ProviderError("Review the redacted payload and explicitly approve sending it first.")
    # Repeat sanitization at the egress boundary, including local model output.
    payload, _ = sanitize(result["ticket"])
    start = time.perf_counter()
    diagnosis = (provider or LocalProvider(settings, cloud=True)).diagnose(payload)
    clean, _ = sanitize(diagnosis.model_dump())
    return {**result, "cloud_diagnosis": clean, "cloud_sent": True,
            "processing_location": "ESCALATED", "cloud_status": "Completed",
            "cloud_latency_ms": round((time.perf_counter()-start)*1000, 2)}
