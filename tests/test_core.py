import json
import httpx
import pytest
from pydantic import ValidationError
from app.config import Settings, Thresholds
from app.models import Diagnosis, Incident, Telemetry
from app.services.telemetry import analyze
from app.services.privacy import redact
from app.services.escalation import decide
from app.services.provider import LocalProvider, ProviderError, SimulationProvider
from app.services.pipeline import run, escalate
from app.services.retrieval import build_index, retrieve

@pytest.fixture
def diagnosis():
    return Diagnosis(issue_category="cpu_saturation", likely_cause="Busy app", confidence=.8, severity="medium",
                     evidence=["cpu_percent"], recommended_actions=["Save work and inspect Task Manager."],
                     needs_escalation=False, escalation_reason=None)

def test_boundaries():
    assert analyze(Telemetry(cpu_percent=90, wifi_signal_percent=35), Thresholds()) == []
    assert len(analyze(Telemetry(cpu_percent=91, wifi_signal_percent=34), Thresholds())) == 2
    with pytest.raises(ValidationError):
        Telemetry(cpu_percent=101)
    with pytest.raises(ValidationError):
        Telemetry(cpu_percent=float("nan"))

@pytest.mark.parametrize("text", ["person@example.com", "192.168.1.2", r"C:\Users\alice\app.log", "/home/alice/foo", "api_key=abcdef", "Bearer topsecret", "hf_abcdefghijkl"])
def test_privacy(text):
    clean, counts = redact(text)
    assert counts and text not in clean

def test_decisions(diagnosis):
    incident = Incident(description="Slow laptop")
    assert decide(diagnosis, incident, ["evidence"]).decision == "LOCAL"
    for change, reason in [({"confidence": .64}, "LOW_CONFIDENCE"), ({"severity": "high"}, "HIGH_RISK"),
                           ({"issue_category": "unknown"}, "UNSUPPORTED_CATEGORY"),
                           ({"insufficient_evidence": True}, "INSUFFICIENT_EVIDENCE")]:
        assert reason in decide(diagnosis.model_copy(update=change), incident, [1]).reason_codes
    assert decide(diagnosis.model_copy(update={"confidence": .65}), incident, [1]).decision == "LOCAL"
    for flag, reason in [("specialist_requested", "USER_REQUESTED"), ("troubleshooting_failed", "TROUBLESHOOTING_FAILED"), ("high_risk", "HIGH_RISK")]:
        assert reason in decide(diagnosis, incident.model_copy(update={flag: True}), [1]).reason_codes

def test_retrieval():
    build_index()
    assert retrieve("battery degradation short runtime")[0]["source"] == "battery_degradation.md"

def test_offline_pipeline(monkeypatch):
    build_index()
    def forbidden(*a, **kw):
        raise AssertionError("No network should be used")
    monkeypatch.setattr(httpx.Client, "post", forbidden)
    r = run(Incident(description="Slow laptop for person@example.com", telemetry={"cpu_percent": 96}), Settings(simulation=True))
    assert r["decision"]["decision"] == "LOCAL"
    assert "person@example.com" not in json.dumps(r)
    assert r["processing_location"] == "SIMULATION"

def test_local_unavailable_never_falls_back(monkeypatch):
    calls = []
    def fail(self, url, **kw):
        calls.append(url)
        raise httpx.ConnectError("offline")
    monkeypatch.setattr(httpx.Client, "post", fail)
    build_index()
    with pytest.raises(ProviderError):
        run(Incident(description="Slow laptop"), Settings(local_model="test", enable_cloud=True))
    assert calls == ["http://localhost:8000/v1/chat/completions"]

def test_bad_json(monkeypatch):
    monkeypatch.setattr(httpx.Client, "post", lambda *a, **k: httpx.Response(200, request=httpx.Request("POST", "http://localhost"), json={"choices": [{"message": {"content": "not json"}}]}))
    with pytest.raises(ProviderError):
        LocalProvider(Settings(local_model="test")).diagnose({})

def test_valid_api(monkeypatch, diagnosis):
    def respond(self, url, **kw):
        assert kw["json"]["model"] == "configured-model"
        return httpx.Response(200, request=httpx.Request("POST", url), json={"choices": [{"message": {"content": diagnosis.model_dump_json()}}]})
    monkeypatch.setattr(httpx.Client, "post", respond)
    assert LocalProvider(Settings(local_model="configured-model")).diagnose({}) == diagnosis

def test_cloud_gates_and_redaction(diagnosis):
    build_index()
    result = run(Incident(description="Slow laptop", telemetry={"cpu_percent": 95}, specialist_requested=True), Settings(), provider=SimulationProvider())
    for settings, consent in [(Settings(), True), (Settings(enable_cloud=True), False), (Settings(enable_cloud=True, simulation=True), True)]:
        with pytest.raises(ProviderError):
            escalate(result, settings, consent)
    class Capture:
        def diagnose(self, payload):
            assert "alice@example.com" not in json.dumps(payload)
            return diagnosis
    result["ticket"]["diagnosis"]["likely_cause"] = "alice@example.com"
    assert escalate(result, Settings(enable_cloud=True), True, Capture())["cloud_sent"]
    result["decision"]["decision"] = "LOCAL"
    with pytest.raises(ProviderError):
        escalate(result, Settings(enable_cloud=True), True, Capture())

def test_remote_primary_rejected():
    with pytest.raises(ProviderError):
        LocalProvider(Settings(local_url="https://example.com/v1", local_model="test")).diagnose({})
