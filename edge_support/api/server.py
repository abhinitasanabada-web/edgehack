"""Private-tunnel API. All retained incidents are redacted, bounded, and expire."""
import copy
import hmac
import secrets
import threading
import time
from collections import OrderedDict
from fastapi import FastAPI, HTTPException, Request, Depends
from starlette.responses import JSONResponse
from app.services.privacy import sanitize
from edge_support.config import Settings
from edge_support.inference.model_client import ModelError
from edge_support.inference.output_schema import IncidentRequest, VerificationRequest, EscalationRequest
from edge_support.services.pipeline import diagnose as run_diagnosis, cloud_second_opinion
from edge_support.actions.verifier import verify

app = FastAPI(title="EdgeSupport integrated API", version="0.2.0")
_records = OrderedDict()
_lock = threading.Lock()
_inference = threading.Semaphore(1)
TTL_SECONDS = 1800

@app.middleware("http")
async def body_limit(request: Request, call_next):
    body = await request.body()
    if len(body)>65536:
        return JSONResponse({"detail":"Request exceeds 64 KB"},status_code=413)
    return await call_next(request)

def settings():
    try:
        return Settings.from_env()
    except (ValueError,OSError):
        raise HTTPException(503,"Invalid server configuration; check the local .env and thresholds") from None

def authorize(request: Request, s: Settings = Depends(settings)):
    if s.action_token and not hmac.compare_digest(request.headers.get("authorization",""),"Bearer "+s.action_token):
        raise HTTPException(401,"A valid endpoint API token is required")
    return s

def prune():
    now=time.monotonic()
    for key in list(_records):
        if now-_records[key]["created"]>TTL_SECONDS: del _records[key]
    while len(_records)>100: _records.popitem(last=False)

@app.get("/health")
def health(s: Settings = Depends(authorize)):
    return {"ok":True,"service":"edgesupport","simulation":s.simulation_mode,
            "cloud_enabled":s.enable_cloud,"sample_count":s.sample_count,
            "large_local_enabled":s.enable_large_local,"auth_enabled":bool(s.action_token)}

@app.post("/diagnose")
def diagnose(request: IncidentRequest,s: Settings = Depends(authorize)):
    if not _inference.acquire(blocking=False): raise HTTPException(429,"Model busy; retry after current incident completes")
    try:
        result=run_diagnosis(request,s)
    except ModelError as exc:
        raise HTTPException(502,str(exc)) from None
    finally:
        _inference.release()
    incident_id=secrets.token_urlsafe(24)
    result["incident_id"]=incident_id
    with _lock:
        _records[incident_id]={"created":time.monotonic(),"result":copy.deepcopy(result),"cloud_attempted":False}
        prune()
    return result

@app.get("/latest")
def latest(s: Settings = Depends(authorize)):
    with _lock:
        prune()
        return copy.deepcopy(next(reversed(_records.values()))["result"]) if _records else {"incident_id":None}

@app.post("/escalate")
def escalate(request: EscalationRequest,s: Settings = Depends(authorize)):
    if not s.enable_cloud or s.simulation_mode or not request.consent:
        raise HTTPException(400,"Cloud is disabled, simulation is active, or approval is missing")
    with _lock:
        prune()
        record=_records.get(request.incident_id)
        if not record: raise HTTPException(404,"Incident expired or unavailable; diagnose again")
        if record["result"]["route"]["decision"]!="ESCALATE": raise HTTPException(400,"Incident does not require escalation")
        if record["cloud_attempted"]: raise HTTPException(409,"Cloud already attempted; no automatic retry")
        record["cloud_attempted"]=True
        result=copy.deepcopy(record["result"])
    try:
        cloud=cloud_second_opinion(result,s,request.consent)
    except ModelError:
        raise HTTPException(502,"Cloud attempt failed; data may have reached the provider. Use the local support ticket. No automatic retry.") from None
    with _lock:
        if request.incident_id in _records:
            _records[request.incident_id]["result"]["cloud_result"]=cloud
    return cloud

@app.post("/verify")
def verification(request: VerificationRequest,s: Settings = Depends(authorize)):
    try:
        result=verify(request.action_id,request.before,request.after,request.target_process,request.action_success)
        return sanitize(result.model_dump())[0]
    except (TypeError,ValueError,AttributeError):
        raise HTTPException(422,"Invalid verification telemetry") from None
