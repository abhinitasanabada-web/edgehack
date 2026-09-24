"""v2 enhancements: every switch keeps the original behaviour by default and does what it claims when on."""
import copy
import json
import httpx
import pytest
from pydantic import ValidationError
from edge_support.config import Settings
from edge_support.inference.output_schema import Diagnosis, IncidentRequest, StrictDiagnosis, diagnosis_schema
from edge_support.inference.model_client import LocalModelClient, ModelError, messages, parse
from edge_support.router.escalation import assess, route_assessment
from edge_support.rag.retriever import retrieve_bm25
from edge_support.services.pipeline import diagnose, cloud_second_opinion

@pytest.fixture
def diag():
    return Diagnosis(issue_category='memory_pressure',diagnosis='High memory use',evidence=['memory_percent is 94'],
        evidence_ids=['signal:memory_percent'],confidence=.9,severity='medium',recommended_action='collect_more_telemetry')

@pytest.fixture
def payload():
    return {"incident":{"telemetry":{"memory_percent":94},"complaint":"apps freeze","logs":"","high_risk":False,
                        "specialist_requested":False,"troubleshooting_failed":False},
            "signals":[{"id":"signal:memory_percent","category":"memory_pressure","field":"memory_percent","value":94}],
            "knowledge":[{"source":"high_memory.md"}]}

class Fake:
    def __init__(self,values): self.values=values;self.calls=[]
    def sample(self,payload,tier='small',sample_index=0):
        self.calls.append(json.dumps(payload))
        v=self.values[sample_index]
        return v,{'tier':tier,'model':'fixture','latency_ms':1,'valid':bool(v)}

def response(body,status=200,url='http://127.0.0.1:8000/v1/chat/completions'):
    return httpx.Response(status,request=httpx.Request('POST',url),json=body)

# --- strict schema / compact prompt ---------------------------------------------------------------

def test_strict_schema_enumerates_ids_and_requires_evidence():
    s=diagnosis_schema(True)
    assert 'enum' in s['properties']['issue_category'] and 'unsupported' in s['properties']['issue_category']['enum']
    assert set(s['properties']['recommended_action']['enum'])>={'flush_dns','no_action_escalate'}
    assert {'issue_category','evidence','evidence_ids','recommended_action'}<=set(s['required'])
    assert 'enum' not in diagnosis_schema(False)['properties']['issue_category']       # default unchanged
    with pytest.raises(ValidationError):
        StrictDiagnosis(issue_category='cpu',diagnosis='x',evidence=[],evidence_ids=[],confidence=.5,severity='low',recommended_action='flush_dns')

def test_compact_prompt_only_when_server_enforces(payload):
    on=Settings(compact_prompt=True)
    assert 'Schema:' not in messages(payload,on,enforced=True)[0]['content']
    assert 'Schema:' in messages(payload,on,enforced=False)[0]['content']
    assert messages(payload)==messages(payload,Settings(),False)                         # default prompt identical

# --- batched sampling (vLLM n + schema) -------------------------------------------------------------

def test_batched_one_request_padding_and_truncation(monkeypatch,diag):
    bodies=[]
    def post(self,url,json=None,**k):
        bodies.append(json)
        return response({'choices':[{'message':{'content':diag.model_dump_json()},'finish_reason':'stop'},
                                    {'message':{'content':'{"trunc'},'finish_reason':'length'}],
                         'usage':{'prompt_tokens':900,'completion_tokens':400,'total_tokens':1300}})
    monkeypatch.setattr(httpx.Client,'post',post)
    out=LocalModelClient(Settings(local_llm_model='m',strict_schema=True,max_output_tokens=450)).sample_many({},'small',3)
    assert len(bodies)==1 and bodies[0]['n']==3 and bodies[0]['max_tokens']==450
    assert bodies[0]['response_format']['json_schema']['schema']['properties']['issue_category'].get('enum')
    assert [d is not None for d,_ in out]==[True,False,False]                           # third sample padded as invalid
    assert out[1][1]['truncated'] and out[2][1].get('missing')

def test_batched_falls_back_without_structured_outputs(monkeypatch,diag):
    bodies=[]
    def post(self,url,json=None,**k):
        bodies.append(copy.deepcopy(json))              # the client reuses one dict for its retry
        if 'response_format' in json: return response({'error':'unsupported response_format'},400)
        return response({'choices':[{'message':{'content':diag.model_dump_json()}}]*3})
    monkeypatch.setattr(httpx.Client,'post',post)
    out=LocalModelClient(Settings(local_llm_model='m',compact_prompt=True)).sample_many({},'small',3)
    assert len(bodies)==2 and 'response_format' not in bodies[1]
    assert 'Schema:' not in bodies[0]['messages'][0]['content'] and 'Schema:' in bodies[1]['messages'][0]['content']
    assert all(d==diag for d,_ in out)

def test_strict_schema_also_constrains_sequential_and_cloud(monkeypatch,diag):
    bodies=[]
    def post(self,url,json=None,**k):
        bodies.append(json); return response({'choices':[{'message':{'content':diag.model_dump_json()},'finish_reason':'stop'}]},url=url)
    monkeypatch.setattr(httpx.Client,'post',post)
    cfg=Settings(strict_schema=True,cloud_llm_base_url='https://cloud.example/v1',cloud_llm_model='c')
    d,m=LocalModelClient(cfg).sample({},'cloud')
    assert d==diag and 'response_format' in bodies[-1] and m['finish_reason']=='stop'
    LocalModelClient(Settings(local_llm_model='m')).sample({})
    assert 'response_format' not in bodies[-1]                                          # default unchanged

# --- lenient parsing ---------------------------------------------------------------------------

@pytest.mark.parametrize('text',[
    '<think>let me check memory</think>{"issue_category":"memory_pressure","diagnosis":"x","confidence":"high","severity":"moderate","recommended_action":"collect_more_telemetry","evidence":"mem 94"}',
    'Sure! Here is the JSON:\n```json\n{"issue_category":"memory_pressure","diagnosis":"x","confidence":0.8,"severity":"medium","recommended_action":"collect_more_telemetry","notes":"extra"}\n```',
    '{"issue_category":"memory_pressure","diagnosis":"x","confidence":"85%","severity":"medium","recommended_action":"collect_more_telemetry","escalate":"false"}'])
def test_lenient_parse_recovers_common_slips(text):
    with pytest.raises(ValueError): parse(text)
    d=parse(text,lenient=True)
    assert d.issue_category=='memory_pressure' and 0<=d.confidence<=1 and d.severity=='medium' and d.escalate is False

def test_lenient_parse_still_rejects_nonsense():
    for bad in ['no json here','<think>ran out of tokens {"issue_category":','[1,2,3]']:
        with pytest.raises(ValueError): parse(bad,lenient=True)

# --- gate modes ----------------------------------------------------------------------------------

def test_majority_gate_ignores_one_stray_sample_but_not_risk(payload,diag):
    hedge=diag.model_copy(update={'escalate':True})
    a=assess([diag]*4+[hedge],5,payload)
    assert route_assessment(a,.8,'any')['decision']=='ESCALATE'
    assert route_assessment(a,.8,'majority')['decision']=='LOCAL'
    a=assess([diag]*4+[None],5,payload)
    assert 'INVALID_MODEL_OUTPUT' in route_assessment(a,.8,'any')['reason_codes']
    assert route_assessment(a,.8,'majority')['decision']=='LOCAL'
    a=assess([diag]*4+[diag.model_copy(update={'severity':'high'})],5,payload)
    assert 'HIGH_RISK' in route_assessment(a,.8,'majority')['reason_codes']
    a=assess([hedge]*3+[diag]*2,5,payload)
    assert 'MODEL_REQUESTED' in route_assessment(a,.8,'majority')['reason_codes']
    assert a['gate_mode']=='any' and a['base_reasons']==a['reasons_by_mode']['any']     # default mode unchanged
    assert len(a['votes'])==5

def test_gate_mode_setting_flows_through_pipeline(diag):
    req=IncidentRequest(complaint='My laptop is slow',telemetry={'memory_percent':94})
    samples=[diag]*2+[diag.model_copy(update={'insufficient_evidence':True})]
    assert diagnose(req,Settings(),Fake(samples))['route']['decision']=='ESCALATE'
    r=diagnose(req,Settings(gate_mode='majority'),Fake(samples))
    assert r['route']['decision']=='LOCAL' and r['route']['gate_mode']=='majority'

# --- retrieval ----------------------------------------------------------------------------------

def test_bm25_ranks_and_namespaces_both_corpora():
    hits=retrieve_bm25('Websites fail to resolve by name dns_network',4)
    assert hits[0]['source']=='runbooks/dns_failure.md'
    sources=[h['source'] for h in retrieve_bm25('laptop hot throttling thermal_throttling',4)]
    assert 'runbooks/thermal_throttling.md' in sources and 'knowledge/thermal_throttling.md' in sources
    assert len(set(sources))==len(sources)
    assert retrieve_bm25('asdf qwerty zxcv')==[]

def test_bm25_citations_pass_the_evidence_gate(diag):
    req=IncidentRequest(complaint='Apps freeze with high memory',telemetry={'memory_percent':94})
    d=diag.model_copy(update={'evidence_ids':['signal:memory_percent','kb:runbooks/high_memory.md']})
    r=diagnose(req,Settings(retrieval='bm25'),Fake([d]*3))
    assert any(k['source']=='runbooks/high_memory.md' for k in r['knowledge'])
    assert r['route']['decision']=='LOCAL' and r['metrics']['evidence_supported']

# --- redaction placement, offline, observability -------------------------------------------------

def test_keep_network_redaction_boundary(diag):
    req=IncidentRequest(complaint='No sites load, token=hunter2secret',telemetry={'network':{'dns_ok':False}},
                        logs='adapter got 169.254.3.4, gateway 10.2.0.1, user bob@corp.com')
    for mode,ip_to_model in (('full',False),('keep_network',True)):
        fake=Fake([diag.model_copy(update={'diagnosis':'saw 10.2.0.1'})]*3)
        r=diagnose(req,Settings(local_redaction=mode),fake)
        assert ('169.254.3.4' in fake.calls[0])==ip_to_model
        assert 'hunter2secret' not in fake.calls[0] and 'bob@corp.com' not in fake.calls[0]
        out=json.dumps(r)
        assert '169.254.3.4' not in out and '10.2.0.1' not in out and 'bob@corp.com' not in out

def test_force_offline_blocks_cloud_and_says_so(diag):
    req=IncidentRequest(complaint='My laptop is slow',telemetry={'memory_percent':94},specialist_requested=True)
    cfg=Settings(enable_cloud=True,force_offline=True)
    r=diagnose(req,cfg,Fake([diag]*3))
    assert 'Uplink down' in r['cloud_status']
    with pytest.raises(ModelError,match='Uplink down'): cloud_second_opinion(r,cfg,True,Fake([diag]))

def test_result_reports_timings_switches_and_votes(diag):
    r=diagnose(IncidentRequest(complaint='My laptop is slow',telemetry={'memory_percent':94}),Settings(),Fake([diag]*3))
    assert {'prepare_ms','small_model_ms','total_ms'}<=set(r['metrics']['timings'])
    assert r['switches']['gate_mode']=='any' and r['switches']['retrieval']=='legacy'
    assert len(r['tiers'][0]['assessment']['votes'])==3

def test_empty_env_values_fall_back_to_defaults(monkeypatch):
    monkeypatch.setenv('CLOUD_PRICE_IN_PER_MTOK','');monkeypatch.setenv('GATE_MODE','majority');monkeypatch.setenv('MAX_OUTPUT_TOKENS','450')
    s=Settings.from_env()
    assert s.cloud_price_in_per_mtok is None and s.gate_mode=='majority' and s.max_output_tokens==450

def test_schema_fallback_is_recorded(monkeypatch,diag):
    def post(self,url,json=None,**k):
        if 'response_format' in json: return response({'error':'response_format unsupported'},400)
        return response({'choices':[{'message':{'content':diag.model_dump_json()}}]*3})
    monkeypatch.setattr(httpx.Client,'post',post)
    out=LocalModelClient(Settings(local_llm_model='m')).sample_many({},'small',3)
    assert all(m['schema_enforced'] is False for _,m in out)

def test_action_plan_carries_only_redacted_model_text(diag):
    leaky=diag.model_copy(update={'recommended_action':'ping 10.9.8.7'})
    r=diagnose(IncidentRequest(complaint='My laptop is slow',telemetry={'memory_percent':94}),
               Settings(local_redaction='keep_network'),Fake([leaky]*3))
    assert '10.9.8.7' not in json.dumps(r['action_plan']) and not r['action_plan']['allowed']

def test_large_tier_outage_reason_not_duplicated(diag):
    other=diag.model_copy(update={'issue_category':'cpu_saturation'})
    class Tiered(Fake):
        def sample(self,payload,tier='small',sample_index=0):
            if tier=='large': raise ModelError('down')
            return super().sample(payload,tier,sample_index)
    r=diagnose(IncidentRequest(complaint='My laptop is slow',telemetry={'memory_percent':94}),
               Settings(enable_large_local=True,large_llm_model='big'),Tiered([diag,diag,other]))
    base=r['tiers'][0]['assessment']['base_reasons']
    assert base.count('LARGE_MODEL_UNAVAILABLE')==1
