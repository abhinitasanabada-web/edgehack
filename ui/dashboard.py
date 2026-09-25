import json
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx
import streamlit as st
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1]/".env")
API_URL=os.getenv("EDGE_SUPPORT_API_URL","http://127.0.0.1:8502")
key=os.getenv("EDGE_SUPPORT_ACTION_TOKEN","")
headers={"Authorization":f"Bearer {key}"} if key else {}

REASONS={"HIGH_RISK":"Possible physical, security or data-loss risk: a person must handle this.",
    "USER_REQUESTED":"The employee asked for a specialist.",
    "TROUBLESHOOTING_FAILED":"An earlier fix did not work, so a person takes over.",
    "HIGH_RISK_ACTION":"The proposed fix is on the high-risk list and needs IT review.",
    "UNSUPPORTED_CATEGORY":"This is not a supported PC problem.",
    "UNKNOWN_ACTION":"The model proposed an action that is not on the approved list.",
    "ACTION_CATEGORY_MISMATCH":"The proposed fix does not match the diagnosed problem.",
    "MODEL_REQUESTED":"The model itself asked for escalation.",
    "INSUFFICIENT_EVIDENCE":"The diagnosis is not backed by a matching telemetry reading or runbook citation.",
    "TELEMETRY_CONFLICT":"The telemetry contradicts the diagnosis (for example, the reading is normal).",
    "INVALID_MODEL_OUTPUT":"At least one model answer was malformed.",
    "INSUFFICIENT_SAMPLES":"One answer alone cannot show agreement.",
    "LOW_AGREEMENT":"The model's repeated answers did not agree enough.",
    "LARGE_MODEL_UNAVAILABLE":"The second local model was unavailable.",
    "MISSING_ROUTING_EVIDENCE":"No routing evidence was supplied."}
HARD={"HIGH_RISK","USER_REQUESTED","TROUBLESHOOTING_FAILED","HIGH_RISK_ACTION"}

def api(path,payload=None):
    with httpx.Client(timeout=3300,trust_env=False) as client:
        r=client.get(API_URL+path,headers=headers) if payload is None else client.post(API_URL+path,json=payload,headers=headers)
    if not r.is_success:
        try: detail=r.json().get("detail","Request failed")
        except ValueError: detail="API request failed"
        raise ValueError(str(detail))
    return r.json()

st.set_page_config(page_title="EdgeSupport",page_icon="🛡️",layout="wide")
st.caption("EDGESUPPORT / SITE-LOCAL IT TRIAGE")
st.title("Diagnose on site. Escalate with evidence.")
try:
    health=api('/health')
except (httpx.HTTPError,ValueError):
    st.error("API unavailable or unauthorized. Start bash run_demo.sh and check the API URL/token.")
    st.stop()
if health['simulation']: st.warning("SIMULATION — fixture responses, no LLM inference. Agreement is synthetic.")
st.caption(f"Samples per tier: {health['sample_count']} · Second local tier: {health['large_local_enabled']} · Cloud enabled: {health['cloud_enabled']}")
link=health.get('uplink') or {}
if link.get('forced_offline'): st.warning("Uplink DOWN (simulated): every answer below is produced on the Nano; escalations stay as local tickets.")
elif link.get('cloud_configured'): st.caption("Cloud uplink: "+("reachable" if link.get('reachable') else "unreachable - local answers still work"))
with st.form("incident"):
    complaint=st.text_area("What is happening?","My laptop becomes slow during video calls")
    telemetry=st.text_area("Telemetry JSON",'{"memory_percent":92,"network":{"dns_ok":true}}')
    logs=st.text_area("Optional logs")
    upload=st.file_uploader("Optional UTF-8 log, up to 20 KB",type=['txt','log'])
    a,b,c=st.columns(3)
    failed=a.checkbox("Troubleshooting failed")
    specialist=b.checkbox("Request specialist")
    risk=c.checkbox("Physical, security or data-loss risk")
    submitted=st.form_submit_button("Diagnose locally",type="primary")
if submitted:
    st.session_state.pop('result',None)
    try:
        if upload:
            if upload.size>20000: raise ValueError("Log exceeds 20 KB")
            logs+='\n'+upload.getvalue().decode('utf-8')
        with st.spinner("Running local evidence and agreement checks…"):
            st.session_state.result=api('/diagnose',dict(complaint=complaint,telemetry=json.loads(telemetry),logs=logs,
                troubleshooting_failed=failed,specialist_requested=specialist,high_risk=risk))
    except (ValueError,httpx.HTTPError) as exc: st.error(str(exc))
if st.button("Load latest redacted endpoint incident"):
    try:
        latest=api('/latest')
        if latest.get('incident_id'): st.session_state.result=latest
        else: st.info("No endpoint incidents yet")
    except (ValueError,httpx.HTTPError): st.error("Could not load latest incident")

@st.fragment(run_every="5s")
def live_status():
    if st.checkbox("Monitor latest endpoint summary (shared demo API)"):
        try:
            latest=api('/latest')
            if latest.get('incident_id'):
                st.write({'incident':latest['incident_id'][-8:], 'mode':latest['processing_location'],
                          'signals':latest['signals'],'route':latest['route']['decision']})
        except (ValueError,httpx.HTTPError): st.warning("Endpoint API unavailable")
live_status()
result=st.session_state.get('result')
if result:
    d=result['diagnosis'];m=result['metrics']
    a,b,c,e,f=st.columns(5)
    a.metric("Processing",result['processing_location'])
    b.metric("Sample agreement",f"{m['agreement']:.0%}")
    c.metric("Total latency",f"{m['latency_ms']:,.0f} ms")
    e.metric("Decision",result['route']['decision'])
    f.metric("System abstained", "YES" if result['route'].get('abstained') else "NO")
    st.caption(f"Model self-report: {d['confidence']:.0%} (not routing probability). Agreement is uncalibrated; samples can share errors.")
    codes=result['route']['reason_codes'];tier0=(result.get('tiers') or [{}])[0].get('assessment') or {}
    with st.container(border=True):
        st.markdown("**How this was decided**")
        n=tier0.get('requested_count') or health['sample_count'];agree=m.get('agreement',0)
        steps=[("Telemetry and runbook evidence checked", bool(m.get('evidence_supported')) and bool(m.get('telemetry_consistent'))),
               (f"Model asked {n} times: {round(agree*n)} of {n} agree (needs {result['route'].get('agreement_threshold',0):.0%})", "LOW_AGREEMENT" not in codes),
               ("Safety gates (risk, specialist request, failed fix)", not HARD.intersection(codes))]
        for text,ok in steps: st.markdown(("✅ " if ok else "⚠️ ")+text)
        if result['route'].get('abstained'):
            st.error("SYSTEM ABSTAINED: no local action was authorized.")
            st.caption(result['route'].get('abstention',{}).get('message','The policy requires review.'))
        elif result['route']['decision']=='LOCAL': st.success("Kept on site: answered by the local model on the Nano.")
        elif HARD.intersection(codes): st.error("Sent to a person (IT support): policy requires human review.")
        else: st.warning("Needs a second opinion: a redacted ticket can go to the cloud with your approval, or to IT support.")
        for code in codes: st.markdown(f"- {REASONS.get(code,code)}")
        votes=[v or {"category":"(malformed answer)"} for v in tier0.get('votes') or []]
        if votes: st.dataframe([{k:v.get(k) for k in ('category','action','severity','escalate','insufficient_evidence')} for v in votes],hide_index=True)
    timings=m.get('timings') or {}
    if timings: st.caption(" · ".join(f"{k.replace('_ms','').replace('_',' ')} {v:,.0f} ms" for k,v in timings.items()))
    st.subheader(d['diagnosis'])

    for step in d['recommended_steps']: st.write('• '+step)
    st.write('Severity: '+d['severity']+' · Proposed action: '+d['recommended_action'])
    if not result['action_plan']['allowed']:
        st.warning("Action status: BLOCKED_BY_POLICY · " + ", ".join(result['action_plan'].get('block_reasons', [])))

    for item in d['evidence']: st.write('• '+item)
    st.info('Reasons: '+(', '.join(result['route']['reason_codes']) or 'Agreement and evidence gates passed'))
    st.write('Redactions:',result['redactions'])
    with st.expander("Evidence, model tiers and per-request tokens"):
        st.json({'signals':result['signals'],'knowledge':result['knowledge'],'tiers':result['tiers'],'metrics':m})
    st.caption("Null token counts mean unavailable, not zero. The dashboard never executes endpoint actions.")
    with st.expander("What would leave the building (redacted ticket)"):
        body=json.dumps(result['ticket'],indent=2)
        st.caption(f"{len(body.encode()):,} bytes · {body.count('[REDACTED_')} redaction markers · raw telemetry and logs stay on the Nano")
        st.code(body,language="json")
    st.download_button("Download support ticket",json.dumps(result['ticket'],indent=2),'support-ticket.json','application/json')
    if result['route']['decision']=='ESCALATE':
        st.info(result['cloud_status'])
        consent=st.checkbox("I reviewed this ticket and approve sending it to the configured cloud provider",key='consent-'+result['incident_id'])
        st.caption("Pattern redaction is incomplete. Review remaining sensitive/proprietary content. Cloud is a second opinion, not permission to execute a fix.")
        if st.button("Send approved cloud escalation",disabled=not health['cloud_enabled'] or result['simulation'] or not consent):
            try:
                result['cloud_result']=api('/escalate',{'incident_id':result['incident_id'],'consent':consent})
            except (ValueError,httpx.HTTPError) as exc: st.error(str(exc))
    if result.get('cloud_result'): st.json(result['cloud_result'])
