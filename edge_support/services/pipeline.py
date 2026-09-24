import time
from app.models import Telemetry
from app.services.privacy import sanitize
from app.services.telemetry import analyze
from app.services.retrieval import retrieve as retrieve_legacy, INDEX
from edge_support.rag.retriever import retrieve
from edge_support.inference.output_schema import Diagnosis
from edge_support.inference.model_client import LocalModelClient, ModelError
from edge_support.router.escalation import assess, route_assessment, HARD_REASONS
from edge_support.actions.registry import get_action

class SimulationClient:
    def sample(self,payload,tier="small",sample_index=0):
        signals=payload["signals"]
        signal=signals[0] if signals else None
        d=Diagnosis(issue_category=signal["category"] if signal else "unsupported",
            diagnosis="SIMULATION: threshold-based fixture, no LLM inference", evidence=[str(signal)] if signal else [],
            evidence_ids=[signal["id"]] if signal else [],confidence=.8 if signal else .3,severity="medium",
            recommended_action="collect_more_telemetry" if signal else "no_action_escalate",
            recommended_steps=["Inspect the supplied evidence; simulation cannot establish a diagnosis."],
            escalate=not bool(signal),insufficient_evidence=not bool(signal))
        return d,{"tier":tier,"model":"SIMULATION","latency_ms":0,"valid":True,
                  "prompt_tokens":None,"completion_tokens":None,"total_tokens":None}

def prepare(request, settings):
    clean,counts=sanitize(request.model_dump())
    metrics={k:v for k,v in clean["telemetry"].items() if k in Telemetry.model_fields}
    signals=[dict(s,id="signal:"+s["field"]) for s in analyze(Telemetry.model_validate(metrics),settings.thresholds)]
    if (clean["telemetry"].get("network") or {}).get("dns_ok") is False:
        signals.append({"id":"signal:dns_ok","category":"dns_network","field":"dns_ok","value":False})
    query=clean["complaint"]+" "+clean["logs"]+" "+" ".join(s["category"] for s in signals)
    knowledge=retrieve(query)
    # Keep both corpora and explain their different lexical score scales.
    if INDEX.exists():
        knowledge += [dict(source=k["source"],content=k["text"],score=k["score"],retrieval="hashed_cosine") for k in retrieve_legacy(query,k=2)]
    payload,extra=sanitize({"incident":clean,"signals":signals,"knowledge":knowledge})
    for key,count in extra.items(): counts[key]=counts.get(key,0)+count
    return payload,counts

def diagnose(request,settings,client=None):
    start=time.perf_counter()
    payload,counts=prepare(request,settings)
    client=client or (SimulationClient() if settings.simulation_mode else LocalModelClient(settings))
    tiers=[]
    stats=[]
    assessment=None
    for tier in (["small","large"] if settings.enable_large_local else ["small"]):
        samples=[]
        for i in range(settings.sample_count):
            try:
                d,m=client.sample(payload,tier,i)
            except ModelError:
                if tier=="small": raise
                # A failed secondary tier cannot trigger cloud automatically or hide the small result.
                assessment["base_reasons"].append("LARGE_MODEL_UNAVAILABLE")
                route=route_assessment(assessment,settings.agreement_threshold)
                tiers.append({"tier":tier,"error":"LARGE_MODEL_UNAVAILABLE","assessment":None})
                break
            samples.append(d)
            stats.append(m)
        else:
            assessment=assess(samples,settings.sample_count,payload)
            route=route_assessment(assessment,settings.agreement_threshold)
            tiers.append({"tier":tier,"assessment":assessment})
            if route["decision"]=="LOCAL" or HARD_REASONS.intersection(route["reason_codes"]): break
            continue
        break
    selected=assessment["selected"]
    if selected is None:
        selected=Diagnosis(issue_category="unsupported",diagnosis="No valid structured diagnosis was returned",
            confidence=0,severity="medium",recommended_action="no_action_escalate",escalate=True,
            insufficient_evidence=True).model_dump()
    action=get_action(selected["recommended_action"])
    clean_result,extra=sanitize({"diagnosis":selected,"payload":payload,"tiers":tiers})
    for key,count in extra.items(): counts[key]=counts.get(key,0)+count
    return {"diagnosis":clean_result["diagnosis"],"route":route,"tiers":clean_result["tiers"],
            "metrics":{"latency_ms":round((time.perf_counter()-start)*1000,2),"requests":stats,
                       "agreement":assessment["agreement"],"evidence_supported":assessment["evidence_supported"],
                       "telemetry_consistent":assessment["telemetry_consistent"]},
            "processing_location":"SIMULATION" if settings.simulation_mode else "LOCAL",
            "simulation":settings.simulation_mode,"cloud_sent":False,
            "cloud_status":"Human/cloud escalation recommended, but cloud processing is disabled." if not settings.enable_cloud else "Awaiting explicit approval",
            "redactions":counts,"knowledge":clean_result["payload"]["knowledge"],"signals":payload["signals"],
            "action_plan":{"action_id":selected["recommended_action"],
                           "allowed":bool(route["decision"]=="LOCAL" and action and not action.high_risk and not settings.simulation_mode),
                           "requires_confirmation":True},
            "ticket":{**clean_result,"route":route}}

def cloud_second_opinion(result,settings,consent,client=None):
    if result["simulation"] or not settings.enable_cloud or not consent or result["route"]["decision"]!="ESCALATE":
        raise ModelError("Cloud requires a real escalation, enabled configuration and explicit consent")
    payload,_=sanitize(result["ticket"])
    d,stats=(client or LocalModelClient(settings)).sample(payload,"cloud",0)
    clean,_=sanitize(d.model_dump() if d else None)
    return {"processing_location":"ESCALATED","cloud_sent":True,"cloud_diagnosis":clean,"metrics":stats,
            "status":"completed" if d else "invalid_output", "human_review_required":True,
            "action_plan":{"allowed":False},"message":"Second opinion only; cloud output never authorizes endpoint actions."}
