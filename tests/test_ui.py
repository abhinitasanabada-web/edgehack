from pathlib import Path
from streamlit.testing.v1 import AppTest
from app.services.retrieval import build_index

def test_web_diagnosis_and_handoff(monkeypatch):
    monkeypatch.setenv("SIMULATION_MODE", "true")
    build_index()
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app/ui.py", default_timeout=30).run()
    assert not app.exception
    app.text_area[0].input("My laptop is very slow")
    app.text_area[1].input('{"cpu_percent":96}')
    app.button[0].click().run()
    assert not app.exception
    assert app.metric[0].value == "SIMULATION"
    assert app.metric[3].value == "LOCAL"
    app.checkbox[1].check()
    app.button[0].click().run()
    assert not app.exception
    assert app.metric[3].value == "ESCALATE"
    assert any("USER_REQUESTED" in x.value for x in app.warning)
    assert any("cloud processing is disabled" in x.value for x in app.info)
