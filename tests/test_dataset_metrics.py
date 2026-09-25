"""Dataset splits, leakage guards and the evaluation metrics added in v2."""
import json
import random
import sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import make_dataset
from eval.evaluate import wilson, choose, rules_category, leaked, run_case, sweep
from edge_support.config import Settings

def load(name): return [json.loads(l) for l in (ROOT/'data/eval'/name).read_text().splitlines()]
base=lambda r:r['incident']['description'].split('. ')[0]

def test_committed_splits_match_the_generator():
    for split,n in (('train',40),('calib',6),('test',14)):
        assert make_dataset.build(split,random.Random(f'7-{split}'),n)==load(f'{split}.jsonl')
    assert make_dataset.build_hard(random.Random('7-hard'),3)==load('test_hard.jsonl')

def test_splits_are_phrasing_disjoint():
    s={n:{base(r) for r in load(f'{n}.jsonl')} for n in ('train','calib','test','test_hard')}
    assert not s['train']&s['test'] and not s['train']&s['calib'] and not s['calib']&s['test']
    assert not s['train']&s['test_hard']

def test_pii_labels_are_what_was_planted():
    rows=load('test.jsonl')
    planted=[r for r in rows if r['pii']]
    assert planted and all(v.replace('\\\\','\\') in r['incident']['description'] or v in r['incident']['description']
                           for r in planted for v in r['pii'])
    assert all(not r['pii'] for r in rows if r not in planted)

def test_hard_set_kinds_and_labels():
    rows=load('test_hard.jsonl')
    kinds={r['kind'] for r in rows}
    assert kinds=={'misleading','distractor','near_threshold','dns_conflict'}
    assert all(r['expected_decision']=='ESCALATE' for r in rows if r['kind'] in {'near_threshold','dns_conflict'})

@pytest.mark.parametrize('split',['data/eval/test.jsonl','data/eval/calib.jsonl','data/eval/test_hard.jsonl'])
def test_build_sft_refuses_scoring_splits(split,monkeypatch):
    sys.path.insert(0,str(ROOT/'finetune'))
    import build_sft
    monkeypatch.setattr(sys,'argv',['build_sft.py','--split',str(ROOT/split),'--output','/tmp/should-not-exist.jsonl'])
    with pytest.raises(SystemExit): build_sft.main()

def test_wilson_and_choose():
    assert wilson(0,0) is None and wilson(5,10)[0]<.5<wilson(5,10)[1]
    curve=lambda pts:[{'threshold':t,'accepted_local':a,'coverage':c,'selective_error':e,'selective_error_ci':None,'unsafe_accepts':u} for t,a,c,e,u in pts]
    sweeps={'any':curve([(.6,50,.5,.10,0),(.8,40,.4,.02,0),(1,30,.3,0,0)]),
            'majority':curve([(.6,60,.6,.03,1),(.8,45,.45,.04,0)])}
    pick=choose(sweeps,.05)
    assert (pick['gate_mode'],pick['threshold'])==('majority',.8)       # highest coverage, zero unsafe, error <= 5%
    assert choose({'any':curve([(1,5,.05,.5,0)])},.05)['threshold']>1   # nothing qualifies -> defer everything

def test_rules_baseline_uses_signals_then_keywords():
    s=Settings()
    case=lambda d,t: {'incident':{'description':d,'telemetry':t,'logs':''}}
    assert rules_category(case('I think the Wi-Fi is slow',{'cpu_percent':97}),s)=='cpu_saturation'
    assert rules_category(case('Battery dies fast',{}),s)=='battery_degradation'
    assert rules_category(case('The coffee machine is broken',{}),s)=='unsupported'

def test_leak_detection_handles_json_escaping():
    assert leaked({'x':r'path C:\Users\alex\AppData'},[r'C:\Users\alex'])==[r'C:\Users\alex']
    assert leaked({'x':'[REDACTED_EMAIL]'},['jordan.lee@example.com'])==[]

def test_run_case_measures_privacy_and_egress():
    case=next(r for r in load('test.jsonl') if r['pii'])
    row=run_case(case,Settings(simulation_mode=True))
    assert row['ok'] and row['pii_planted']>=1 and row['pii_leaked']==[]
    assert 0<row['hybrid_bytes'] and 0<row['cloud_only_bytes'] and row['hybrid_chars']<row['hybrid_bytes']
    curve=sweep([row],[0,1],'majority')
    assert len(curve)==2 and curve[0]['incidents']==1

def test_batched_usage_is_counted_once(monkeypatch):
    """vLLM reports usage for all n choices together; per-sample copies must not be summed n times."""
    import eval.evaluate as ev
    from edge_support.inference.output_schema import Diagnosis
    d=Diagnosis(issue_category='memory_pressure',diagnosis='x',evidence=['m'],evidence_ids=['signal:memory_percent'],
                confidence=.9,severity='medium',recommended_action='collect_more_telemetry')
    stats={'tier':'small','model':'m','latency_ms':1,'valid':True,'batched_samples':3,'prompt_tokens':1000,'completion_tokens':450}
    class Batched:
        def sample_many(self,payload,tier,n): return [(d,dict(stats))]*n
    real=ev.diagnose
    monkeypatch.setattr(ev,'diagnose',lambda req,s: real(req,s,Batched()))
    case=next(r for r in load('test.jsonl') if r['kind']=='telemetry')
    row=ev.run_case(case,Settings(local_llm_model='m'))
    assert row['completion_tokens']==450 and row['prompt_tokens']==1000

def test_escalation_egress_is_the_real_request_body():
    """Hybrid bytes = the JSON body cloud_second_opinion would send (system prompt + minimal redacted payload)."""
    import json
    from edge_support.inference.model_client import messages
    from edge_support.services.pipeline import cloud_payload, diagnose
    from edge_support.inference.output_schema import IncidentRequest
    r=diagnose(IncidentRequest(complaint='Something is wrong with my computer'),Settings(simulation_mode=True))
    sent=messages(cloud_payload(r),Settings(),False)
    assert 'tiers' not in cloud_payload(r) and set(cloud_payload(r))=={'payload','diagnosis','route'}
    assert len(json.dumps(sent))>len(json.dumps(cloud_payload(r)))       # the system prompt is part of what leaves

def test_threshold_grid_keeps_exact_fractions():
    from edge_support.router.escalation import route_assessment
    a={'base_reasons':[],'requested_count':3,'agreement':2/3}
    assert route_assessment(a,2/3)['decision']=='LOCAL' and route_assessment(a,round(2/3,4))['decision']=='ESCALATE'

@pytest.mark.parametrize('small_correct,final_correct', [(False, True), (True, False)])
def test_threshold_sweep_scores_small_tier_not_final_tier(small_correct, final_correct):
    row = {'assessment': {'selected': {'issue_category': 'memory_pressure' if small_correct else 'cpu_saturation'},
                          'base_reasons': [], 'requested_count': 5, 'agreement': .8},
           'expected_category': 'memory_pressure', 'category_correct': final_correct,
           'expected_decision': 'LOCAL', 'resolved_by': 'large'}
    curve = sweep([row], [.8, 1])
    assert curve[0]['selective_error'] == (0 if small_correct else 1)
    assert curve[1]['accepted_local'] == 0
    selected = choose({'any': curve}, 0)
    assert selected['threshold'] == (.8 if small_correct else 1.01)


def test_calibrated_defer_all_threshold_loads_in_runtime(monkeypatch):
    from edge_support.router.escalation import route_assessment
    pick = choose({'any': []}, .05)
    monkeypatch.setenv('AGREEMENT_THRESHOLD', str(pick['threshold']))
    settings = Settings.from_env()
    assessment = {'base_reasons': [], 'requested_count': 3, 'agreement': 1.0}
    assert route_assessment(assessment, settings.agreement_threshold)['decision'] == 'ESCALATE'
    with pytest.raises(ValueError):
        Settings(agreement_threshold=1.02)


def test_defer_all_evaluation_has_operating_point(tmp_path):
    import subprocess
    output = tmp_path / 'report.json'
    subprocess.run([sys.executable, str(ROOT / 'eval/evaluate.py'), '--simulate', '--limit', '1',
                    '--threshold', '1.01', '--output', str(output)], check=True, capture_output=True)
    report = json.loads(output.read_text())
    from compare_runs import row
    summary = row(output, report)
    assert summary['local_rate'] == 0
    assert summary['abstention_rate'] == 1
    assert summary['unsafe_accepts'] == 0
    assert summary['unsafe_action_blocks'] == report['unsafe_action_blocks']
