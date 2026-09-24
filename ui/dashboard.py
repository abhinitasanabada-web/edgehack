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
    a,b,c,e=st.columns(4)
    a.metric("Processing",result['processing_location'])
    b.metric("Sample agreement",f"{m['agreement']:.0%}")
    c.metric("Total latency",f"{m['latency_ms']:,.0f} ms")
    e.metric("Decision",result['route']['decision'])
    st.caption(f"Model self-report: {d['confidence']:.0%} (not routing probability). Agreement is uncalibrated; samples can share errors.")
    st.subheader(d['diagnosis'])

    for step in d['recommended_steps']: st.write('• '+step)
    st.write('Severity: '+d['severity']+' · Proposed action: '+d['recommended_action'])

    for item in d['evidence']: st.write('• '+item)
    st.info('Reasons: '+(', '.join(result['route']['reason_codes']) or 'Agreement and evidence gates passed'))
    st.write('Redactions:',result['redactions'])
    with st.expander("Evidence, model tiers and per-request tokens"):
        st.json({'signals':result['signals'],'knowledge':result['knowledge'],'tiers':result['tiers'],'metrics':m})
    st.caption("Null token counts mean unavailable, not zero. The dashboard never executes endpoint actions.")
    with st.expander("Review redacted support ticket"):
        st.json(result['ticket'])
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
