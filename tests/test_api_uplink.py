"""API additions: uplink status in /health and the offline guard on /escalate. Needs FastAPI (runs on the Nano)."""
import pytest
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient
from edge_support.api import server
from edge_support.config import Settings


def client(cfg):
    server._records.clear()
    server.app.dependency_overrides[server.settings] = lambda: cfg
    return TestClient(server.app)


def test_health_reports_uplink_and_switches():
    try:
        c = client(Settings(simulation_mode=True, force_offline=True, gate_mode="majority"))
        body = c.get("/health").json()
        assert body["uplink"]["forced_offline"] and body["uplink"]["reachable"] is False
        assert body["switches"]["gate_mode"] == "majority"
    finally:
        server.app.dependency_overrides.clear()


def test_escalate_refuses_while_offline():
    try:
        c = client(Settings(enable_cloud=True, force_offline=True))
        r = c.post("/escalate", json={"incident_id": "anything", "consent": True})
        assert r.status_code == 503 and "nothing was sent" in r.json()["detail"]
    finally:
        server.app.dependency_overrides.clear()
