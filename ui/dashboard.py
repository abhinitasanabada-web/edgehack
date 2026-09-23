from __future__ import annotations

import json
import os

import httpx
import streamlit as st


API_URL = os.getenv("EDGE_SUPPORT_API_URL", "http://127.0.0.1:8502")

st.set_page_config(page_title="EdgeSupport", page_icon="🛠️", layout="wide")
st.title("EdgeSupport")
st.caption("Edge-first IT support: diagnose locally, remediate through a controlled endpoint agent.")

complaint = st.text_area("What is happening?", "My laptop becomes very slow during video calls")
telemetry_text = st.text_area("Endpoint telemetry JSON", '{"memory_percent": 92, "network": {"dns_ok": true}}')

if st.button("Diagnose locally", type="primary"):
    try:
        telemetry = json.loads(telemetry_text or "{}")
        with httpx.Client(timeout=120, trust_env=False) as client:
            response = client.post(f"{API_URL}/diagnose", json={"complaint": complaint, "telemetry": telemetry})
            response.raise_for_status()
        st.session_state["result"] = response.json()
    except Exception as exc:
        st.error(f"Diagnosis failed: {exc}")

result = st.session_state.get("result")
if result:
    diagnosis = result["diagnosis"]
    route = result["route"]
    st.success(f"Primary inference: LOCAL | Route: {route['decision']}")
    left, right = st.columns(2)
    with left:
        st.subheader(diagnosis["diagnosis"])
        st.write(f"**Confidence:** {diagnosis['confidence']:.0%}")
        st.write(f"**Severity:** {diagnosis['severity']}")
        st.write(f"**Recommended action:** `{diagnosis['recommended_action']}`")
    with right:
        st.subheader("Evidence")
        for item in diagnosis["evidence"]:
            st.write(f"- {item}")
        st.info(route["reason"])
    st.warning("The dashboard displays the approved action plan. The Windows endpoint collector executes actions only when explicitly run with confirmation.")

