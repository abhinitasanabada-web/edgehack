import copy
import json
import pytest
import httpx
from pydantic import ValidationError
from fastapi.testclient import TestClient
from edge_support.config import Settings
from edge_support.inference.output_schema import Diagnosis, IncidentRequest
from edge_support.inference.model_client import LocalModelClient, ModelError
from edge_support.services.pipeline import diagnose, prepare, cloud_second_opinion
from edge_support.router.escalation import assess, route_assessment
from edge_support.actions.verifier import verify
from edge_support.actions.safe_actions import execute_action
from edge_support.api import server
from eval.evaluate import sweep

@pytest.fixture
def req():
    return IncidentRequest(complaint='My laptop is slow',telemetry={'memory_percent':94})

@pytest.fixture
def diag():
    return Diagnosis(issue_category='memory_pressure',diagnosis='High memory use',evidence=['memory_percent is 94'],
        evidence_ids=['signal:memory_percent'],confidence=.99,severity='medium',recommended_action='collect_more_telemetry')

class Fake:
    def __init__(self,values): self.values=values;self.calls=[]
    def sample(self,payload,tier='small',sample_index=0):
        self.calls.append((tier,copy.deepcopy(payload)))
        value=self.values[tier][sample_index]
        if isinstance(value,Exception): raise value
        return value,{'tier':tier,'model':'fixture','latency_ms':1,'valid':bool(value),'prompt_tokens':100,'completion_tokens':30,'total_tokens':130}

def test_valid_real_mode_agreement_and_metrics(req,diag):
    client=Fake({'small':[diag]*3})
    result=diagnose(req,Settings(),client)
    assert result['route']['decision']=='LOCAL'
    assert result['metrics']['agreement']==1
    assert len(result['metrics']['requests'])==3
    assert not result['simulation']

@pytest.mark.parametrize('field,value,reason',[
    ('severity','critical','HIGH_RISK'),('severity','high','HIGH_RISK'),
    ('recommended_action','restart_dns_client','HIGH_RISK_ACTION'),
    ('recommended_action','arbitrary_command','UNKNOWN_ACTION'),
    ('recommended_action','flush_dns','ACTION_CATEGORY_MISMATCH'),
    ('issue_category','unknown','UNSUPPORTED_CATEGORY'),
    ('evidence_ids',['made_up'],'INSUFFICIENT_EVIDENCE'),
    ('insufficient_evidence',True,'INSUFFICIENT_EVIDENCE'),('escalate',True,'MODEL_REQUESTED')])
def test_policy(req,diag,field,value,reason):
    changed=diag.model_copy(update={field:value})
    result=diagnose(req,Settings(),Fake({'small':[changed]*3}))
    assert reason in result['route']['reason_codes']
    assert not result['action_plan']['allowed']

@pytest.mark.parametrize('field,reason',[('high_risk','HIGH_RISK'),('specialist_requested','USER_REQUESTED'),('troubleshooting_failed','TROUBLESHOOTING_FAILED')])
def test_hard_handoff_does_not_use_large(req,diag,field,reason):
    client=Fake({'small':[diag]*3})
    result=diagnose(req.model_copy(update={field:True}),Settings(enable_large_local=True,large_llm_model='bigger'),client)
    assert reason in result['route']['reason_codes']
    assert all(t=='small' for t,p in client.calls)

def test_telemetry_conflict(req,diag):
    req.telemetry={'memory_percent':20}
    result=diagnose(req,Settings(),Fake({'small':[diag]*3}))
    assert 'TELEMETRY_CONFLICT' in result['route']['reason_codes']

def test_disagreement_ignores_high_self_report(req,diag):
    other=diag.model_copy(update={'issue_category':'cpu_saturation'})
    result=diagnose(req,Settings(),Fake({'small':[diag,diag,other]}))
    assert result['metrics']['agreement']==pytest.approx(2/3)
    assert result['route']['decision']=='ESCALATE'

def test_optional_large_tier(req,diag):
    other=diag.model_copy(update={'issue_category':'cpu_saturation'})
    client=Fake({'small':[diag,diag,other],'large':[diag]*3})
    result=diagnose(req,Settings(enable_large_local=True,large_llm_model='large'),client)
    assert result['route']['decision']=='LOCAL'
    assert [t['tier'] for t in result['tiers']]==['small','large']

def test_secondary_outage_and_primary_outage(req,diag):
    other=diag.model_copy(update={'issue_category':'cpu_saturation'})
    client=Fake({'small':[diag,diag,other],'large':[ModelError('down')]})
    result=diagnose(req,Settings(enable_large_local=True,large_llm_model='large'),client)
    assert 'LARGE_MODEL_UNAVAILABLE' in result['route']['reason_codes']
    assert not result['cloud_sent']
    with pytest.raises(ModelError): diagnose(req,Settings(enable_cloud=True),Fake({'small':[ModelError('down')]}))

def test_invalid_samples_count_and_single_sample(req,diag):
    result=diagnose(req,Settings(),Fake({'small':[diag,None,diag]}))
    assert 'INVALID_MODEL_OUTPUT' in result['route']['reason_codes']
    assert result['metrics']['agreement']==pytest.approx(2/3)
    assert len(result['metrics']['requests'])==3
    result=diagnose(req,Settings(sample_count=1),Fake({'small':[diag]}))
    assert 'INSUFFICIENT_SAMPLES' in result['route']['reason_codes']

def test_all_invalid_with_high_risk_no_large(req):
    req.high_risk=True
    result=diagnose(req,Settings(enable_large_local=True,large_llm_model='big'),Fake({'small':[None]*3}))
    assert 'HIGH_RISK' in result['route']['reason_codes']
    assert len(result['tiers'])==1

def test_sanitization_entire_flow(req,diag):
    req.complaint='Laptop slow for user@example.com token=my_private_secret'
    client=Fake({'small':[diag.model_copy(update={'diagnosis':'user@example.com'})]*3})
    result=diagnose(req,Settings(),client)
    assert 'user@example.com' not in json.dumps(result)
    assert 'my_private_secret' not in json.dumps(client.calls)
    assert result['redactions']

def test_api_simulation_null_telemetry_auth_cloud(monkeypatch):
    server._records.clear()
    cfg=Settings(simulation_mode=True,action_token='test-only')
    server.app.dependency_overrides[server.settings]=lambda:cfg
    try:
        c=TestClient(server.app)
        assert c.get('/health').status_code==401
        headers={'Authorization':'Bearer test-only'}
        r=c.post('/diagnose',headers=headers,json={'complaint':'Laptop slow','telemetry':{'memory_percent':None,'network':{'dns_ok':True}}})
        assert r.status_code==200
        assert r.json()['processing_location']=='SIMULATION'
        assert not r.json()['action_plan']['allowed']
        assert c.get('/latest',headers=headers).json()['incident_id']==r.json()['incident_id']
        assert c.post('/escalate',headers=headers,json={'incident_id':r.json()['incident_id'],'consent':True}).status_code==400
        assert c.post('/diagnose',headers=headers,json={'complaint':'test incident','telemetry':{'cpu_percent':101}}).status_code==422
        assert c.post('/diagnose',headers=headers,content='x'*65537).status_code==413
    finally: server.app.dependency_overrides.clear()

def test_cloud_gates_egress_and_no_action(req,diag):
    req.specialist_requested=True
    result=diagnose(req,Settings(),Fake({'small':[diag]*3}))
    for config,consent in [(Settings(),True),(Settings(enable_cloud=True),False)]:
        with pytest.raises(ModelError): cloud_second_opinion(result,config,consent)
    result['ticket']['diagnosis']['diagnosis']='api_key=secretvalue user@example.com'
    cloud=Fake({'cloud':[diag]})
    output=cloud_second_opinion(result,Settings(enable_cloud=True),True,cloud)
    assert 'secretvalue' not in json.dumps(cloud.calls)
    assert 'user@example.com' not in json.dumps(cloud.calls)
    assert output['cloud_sent'] and output['human_review_required'] and not output['action_plan']['allowed']

def test_cloud_server_stored_decision_once(req,diag,monkeypatch):
    server._records.clear()
    cfg=Settings(enable_cloud=True)
    server.app.dependency_overrides[server.settings]=lambda:cfg
    req.specialist_requested=True
    stored=diagnose(req,cfg,Fake({'small':[diag]*3}))
    monkeypatch.setattr(server,'run_diagnosis',lambda *a:copy.deepcopy(stored))
    monkeypatch.setattr(server,'cloud_second_opinion',lambda *a:{'cloud_sent':True})
    try:
        c=TestClient(server.app)
        ident=c.post('/diagnose',json=req.model_dump()).json()['incident_id']
        assert c.post('/escalate',json={'incident_id':'forged','consent':True}).status_code==404
        assert c.post('/escalate',json={'incident_id':ident,'consent':True}).status_code==200
        assert c.post('/escalate',json={'incident_id':ident,'consent':True}).status_code==409
    finally: server.app.dependency_overrides.clear()

def test_precise_verification():
    before={'processes':[{'name':'notepad'},{'name':'other'}]}
    after={'processes':[{'name':'notepad'}]}
    assert not verify('close_demo_process',before,after,'notepad',True).verified
    assert verify('close_demo_process',before,{'processes':[]},'notepad',True).verified
    assert not verify('flush_dns',{'network':{'dns_ok':True}},{'network':{'dns_ok':True}},action_success=True).verified
    assert verify('flush_dns',{'network':{'dns_ok':False}},{'network':{'dns_ok':True}},action_success=True).verified
    assert not verify('clear_temp',{}, {'disk':{'edge_temp_bytes':0}},action_success=True).verified
    assert not execute_action('clear_temp',dry_run=False).executed

def test_adapter_usage_malformed_and_local_url(monkeypatch,diag):
    def respond(self,url,**kwargs):
        return httpx.Response(200,request=httpx.Request('POST',url),json={'choices':[{'message':{'content':diag.model_dump_json()}}], 'usage':{'prompt_tokens':12,'completion_tokens':9,'total_tokens':21}})
    monkeypatch.setattr(httpx.Client,'post',respond)
    d,m=LocalModelClient(Settings(local_llm_model='test')).sample({})
    assert d==diag and m['total_tokens']==21
    with pytest.raises(ModelError): LocalModelClient(Settings(local_llm_base_url='https://example.com/v1',local_llm_model='test')).sample({})
    monkeypatch.setattr(httpx.Client,'post',lambda *a,**k:httpx.Response(200,request=httpx.Request('POST','http://localhost'),json={'choices':[{'message':{'content':'invalid'}}],'usage':{'total_tokens':30}}))
    d,m=LocalModelClient(Settings(local_llm_model='test')).sample({})
    assert d is None and m['total_tokens']==30 and not m['valid']

def test_sweep_coverage_error_no_fabricated_metrics(req,diag):
    payload,_=prepare(req,Settings())
    a=assess([diag]*3,3,payload)
    rows=[{'assessment':a,'category_correct':True,'expected_decision':'LOCAL'},{'ok':False}]
    curve=sweep(rows,[.5,1])
    assert all(r['coverage']==.5 and r['deferred']==1 for r in curve)

@pytest.mark.parametrize('telemetry',[{'memory_percent':float('nan')},{'network':{'dns_ok':'false'}},{'processes':[1]}])
def test_input_schema(telemetry):
    with pytest.raises(ValidationError): IncidentRequest(complaint='test incident',telemetry=telemetry)
