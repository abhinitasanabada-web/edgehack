from pathlib import Path
import httpx
from streamlit.testing.v1 import AppTest
from edge_support.config import Settings
from edge_support.inference.output_schema import IncidentRequest
from edge_support.services.pipeline import diagnose

def test_dashboard_labels_simulation_and_cloud_disabled(monkeypatch):
    cfg=Settings(simulation_mode=True)
    result=diagnose(IncidentRequest(complaint='My laptop is slow',telemetry={'memory_percent':94}),cfg)
    result['incident_id']='fixture-id'
    def respond(self,url,**kwargs):
        content={'ok':True,'simulation':True,'sample_count':3,'large_local_enabled':False,'cloud_enabled':False} if url.endswith('/health') else result
        return httpx.Response(200,request=httpx.Request('GET',url),json=content)
    monkeypatch.setattr(httpx.Client,'get',respond)
    monkeypatch.setattr(httpx.Client,'post',respond)
    app=AppTest.from_file(Path(__file__).resolve().parents[1]/'ui/dashboard.py',default_timeout=30).run()
    assert not app.exception
    assert any('SIMULATION' in w.value for w in app.warning)
    app.button[0].click().run()
    assert not app.exception
    assert app.metric[0].value=='SIMULATION'
    assert app.metric[3].value=='LOCAL'
