"""Local-only measurements and threshold sweep. Never calls cloud or executes actions."""
import argparse
import csv
import json
import math
import statistics
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from edge_support.config import Settings, ROOT
from edge_support.inference.output_schema import IncidentRequest
from edge_support.services.pipeline import diagnose
from edge_support.inference.model_client import ModelError
from edge_support.router.escalation import route_assessment

def quantile(values,q):
    return sorted(values)[max(0,math.ceil(len(values)*q)-1)] if values else None

def sweep(rows,thresholds):
    results=[]
    for threshold in thresholds:
        valid=[r for r in rows if r.get('assessment')]
        accepted=[r for r in valid if route_assessment(r['assessment'],threshold)['decision']=='LOCAL']
        results.append({'threshold':threshold,'incidents':len(rows),'accepted_local':len(accepted),
            'coverage':len(accepted)/len(rows) if rows else None,
            'selective_error':sum(not r['category_correct'] for r in accepted)/len(accepted) if accepted else None,
            'unsafe_accepts':sum(r['expected_decision']=='ESCALATE' for r in accepted),
            'deferred':len(rows)-len(accepted)})
    return results

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--simulate',action='store_true')
    parser.add_argument('--samples',type=int,choices=[1,3,5],default=3)
    parser.add_argument('--dataset',default=str(ROOT/'data/evaluation.json'))
    parser.add_argument('--output',default='reports/integrated-benchmark.json')
    parser.add_argument('--threshold',type=float,default=.8)
    parser.add_argument('--warmup',action='store_true')
    parser.add_argument('--large',action='store_true',help='keep the second local tier enabled (measures the full ladder)')
    parser.add_argument('--limit',type=int,help='only the first N cases (quick pass)')
    args=parser.parse_args()
    settings=Settings.from_env().model_copy(update={'simulation_mode':args.simulate,'sample_count':args.samples,
        'agreement_threshold':args.threshold,'enable_cloud':False,
        'enable_large_local':args.large and Settings.from_env().enable_large_local})
    if not 0<=args.threshold<=1: parser.error('threshold must be in [0,1]')
    text=Path(args.dataset).read_text()
    cases=json.loads(text) if args.dataset.endswith('.json') else [json.loads(l) for l in text.splitlines() if l.strip()]
    cases=cases[:args.limit]
    if not cases: parser.error('dataset must contain cases')
    def incident(case):
        data=dict(case['incident'])
        data['complaint']=data.pop('description')
        return IncidentRequest.model_validate(data)
    if args.warmup: diagnose(incident(cases[0]),settings)
    rows=[]
    for case in cases:
        try:
            r=diagnose(incident(case),settings)
            a=r['tiers'][0]['assessment']
            rows.append({'id':case['id'],'ok':True,'expected_category':case['expected_category'],
                'expected_decision':case['expected_decision'],
                'category_correct':r['diagnosis']['issue_category']==case['expected_category'],
                'route_correct':r['route']['decision']==case['expected_decision'],
                'action_correct':r['diagnosis']['recommended_action']==case['expected_action'] if 'expected_action' in case else None,
                'resolved_by':r['tiers'][-1]['tier'],
                'assessment':a,'route':r['route'],'metrics':r['metrics']})
        except (ModelError,ValueError) as exc:
            rows.append({'id':case['id'],'ok':False,'error':'Local inference or input failed'})
    good=[r for r in rows if r['ok']]
    latency=[r['metrics']['latency_ms'] for r in good]
    report={'mode':'SIMULATION_NOT_MODEL_BENCHMARK' if args.simulate else 'LOCAL_MODEL',
        'model':settings.local_llm_model if not args.simulate else 'fixture','sample_count':args.samples,
        'threshold':args.threshold,'dataset':Path(args.dataset).name,'cases':len(rows),'success_rate':len(good)/len(rows),
        'category_accuracy':sum(r.get('category_correct',False) for r in rows)/len(rows),
        'route_accuracy':sum(r.get('route_correct',False) for r in rows)/len(rows),
        'action_accuracy':(sum(bool(r.get('action_correct')) for r in rows)/len(rows)) if any(r.get('action_correct') is not None for r in rows) else None,
        'local_rate':sum(r.get('route',{}).get('decision')=='LOCAL' for r in good)/len(rows),
        'resolved_by_large':sum(r.get('resolved_by')=='large' and r['route']['decision']=='LOCAL' for r in good),
        'p50_ms':statistics.median(latency) if latency else None,'p95_ms':quantile(latency,.95),
        'cloud_requests':0,'energy_joules':None,'cloud_cost':None,
        'limitations':'Small-tier deferral curve only; no counterfactual large/cloud cost or energy measured. Failures remain deferred.',
        'sweep':sweep(rows,[0,.4,.6,.7,.8,.9,1]),'rows':rows}
    output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,indent=2))
    with output.with_suffix('.csv').open('w') as f:
        writer=csv.DictWriter(f,fieldnames=list(report['sweep'][0]))
        writer.writeheader();writer.writerows(report['sweep'])
    print(json.dumps({k:v for k,v in report.items() if k not in {'rows','sweep'}},indent=2))
    if not good: raise SystemExit(1)
if __name__=='__main__': main()
