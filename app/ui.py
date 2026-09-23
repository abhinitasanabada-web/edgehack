import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import streamlit as st
from pydantic import ValidationError
from app.config import Settings
from app.models import Incident
from app.services.pipeline import run, escalate
from app.services.provider import ProviderError

st.set_page_config(page_title="EdgeSupport | Local IT triage", page_icon="🛡️", layout="wide")
st.caption("EDGESUPPORT  /  HP EDGE AI HACKATHON")
st.title("Your IT support starts here.")
st.write("Describe the problem. Get evidence-backed troubleshooting on your local device.")
try:
    settings = Settings.from_env()
except (ValueError, OSError):
    st.error("Invalid configuration. Check .env and data/thresholds.json.")
    st.stop()
with st.sidebar:
    st.header("Processing controls")
    st.success("Mode · SIMULATION" if settings.simulation else "Primary inference · LOCAL")
    st.write("Cloud enabled" if settings.enable_cloud else "Cloud processing disabled")
    st.caption("Cloud requires an escalation decision and your explicit send action.")
    st.write(f"Confidence threshold: {settings.confidence_threshold:.0%}")
    st.caption("Confidence is model-reported and uncalibrated. Thresholds are demo heuristics.")
    with st.expander("Telemetry thresholds"):
        st.json(settings.thresholds.model_dump())
    st.caption("Original inputs remain in this local app session. No incident database or automatic log export.")
if settings.simulation:
    st.warning("SIMULATION MODE — synthetic fixture responses; no LLM inference or Nano performance measurement.")
with st.form("incident"):
    description = st.text_area("What is happening?", placeholder="My laptop becomes very slow during video calls…", height=110)
    left, right = st.columns(2)
    with left:
        telemetry = st.text_area("Optional telemetry JSON", value="{}", height=170)
        st.caption('Example: {"cpu_percent": 96, "memory_percent": 91}')
    with right:
        logs = st.text_area("Optional log text", height=105)
        log_file = st.file_uploader("Or attach a UTF-8 log (up to 20 KB)", type=["txt", "log"])
    a,b,c = st.columns(3)
    failed = a.checkbox("Troubleshooting already failed")
    specialist = b.checkbox("Request specialist support")
    risk = c.checkbox("Physical, security or data-loss risk")
    submitted = st.form_submit_button("Diagnose locally", type="primary")
if submitted:
    st.session_state.pop("result", None)
    try:
        if log_file is not None:
            if log_file.size > 20000:
                raise ValueError("Log upload exceeds 20 KB.")
            logs += "\n" + log_file.getvalue().decode("utf-8")
        incident = Incident(description=description.strip(), telemetry=json.loads(telemetry or "{}"), logs=logs,
                            troubleshooting_failed=failed, specialist_requested=specialist, high_risk=risk)
        with st.spinner("Analyzing telemetry, retrieving local evidence, and asking the local model…"):
            st.session_state.result = run(incident, settings)
    except ProviderError as exc:
        st.error(str(exc))
    except (ValueError, ValidationError, OSError):
        st.error("Unable to process input. Check description length, telemetry field names/ranges, UTF-8 logs (20 KB maximum), and the local index. Run scripts/build_index.py if needed.")
if "result" in st.session_state:
    result = st.session_state.result
    diagnosis = result["diagnosis"]
    st.divider()
    a,b,c,d = st.columns(4)
    a.metric("Processing location", result["processing_location"])
    b.metric("Local confidence", f'{diagnosis["confidence"]:.0%}')
    c.metric("Local total latency", f'{result["latency_ms"]:,.0f} ms')
    d.metric("Routing decision", result["decision"]["decision"])
    st.subheader(diagnosis["issue_category"].replace("_", " ").title())
    st.write(diagnosis["likely_cause"])
    st.caption(f'Severity: {diagnosis["severity"]} · Local inference: {result["inference_ms"]:,.0f} ms')
    for i, action in enumerate(diagnosis["recommended_actions"], 1):
        st.write(f"{i}. {action}")
    st.info("Redaction occurred: " + (json.dumps(result["redactions"]) if result["redactions"] else "No matching patterns found"))
    with st.expander("Diagnosis evidence and telemetry signals"):
        st.write(diagnosis["evidence"])
        st.json(result["signals"])
    with st.expander("Retrieved local knowledge"):
        for hit in result["retrieved"]:
            st.markdown(f'**{hit["source"]}** · cosine similarity {hit["score"]:.3f}')
            st.text(hit["text"])
    if result["decision"]["decision"] == "ESCALATE":
        st.warning("Escalation reasons: " + ", ".join(result["decision"]["reason_codes"]))
        if diagnosis["escalation_reason"]:
            st.write(diagnosis["escalation_reason"])
        if not settings.enable_cloud:
            st.info("Human/cloud escalation recommended, but cloud processing is disabled.")
        with st.expander("Review redacted support payload before export or cloud processing"):
            st.json(result["ticket"])
        st.caption("Pattern redaction is incomplete DLP. Review for names, IPv6, proprietary data and other sensitive content. No ticket is sent to a human automatically.")
        st.download_button("Download redacted support ticket", json.dumps(result["ticket"], indent=2), "support-ticket.json", "application/json")
        consent = st.checkbox("I reviewed the payload and approve sending it to the configured cloud provider.")
        if st.button("Send escalation to cloud", disabled=not settings.enable_cloud or settings.simulation or not consent or result["cloud_sent"]):
            try:
                with st.spinner("Processing approved cloud escalation…"):
                    st.session_state.result = escalate(result, settings, consent=consent)
                st.rerun()
            except ProviderError as exc:
                st.error(str(exc))
                st.warning("Cloud escalation did not complete; request data may have reached the configured provider. Local results remain available. Use the support ticket for human review.")
    if result.get("cloud_diagnosis"):
        st.subheader("Cloud second opinion")
        st.json(result["cloud_diagnosis"])
        st.caption(f'Cloud round trip: {result["cloud_latency_ms"]:,.0f} ms')
