"""Local measurements, threshold sweep, calibration and the brief's metrics.

Never executes endpoint actions. Calls the cloud ONLY with --cloud-baseline / --cloud-escalations (explicit
consent for a synthetic benchmark). Typical Nano flow (see docs/NANO_RUNBOOK.md):

  evaluate.py --dataset data/eval/calib.jsonl --calibrate --threshold-out reports/threshold.json
  evaluate.py --dataset data/eval/test.jsonl  --threshold-file reports/threshold.json --output reports/test.json
"""
import argparse
import csv
import json
import math
import shutil
import statistics
import subprocess
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.models import Telemetry
from app.services.privacy import sanitize
from app.services.telemetry import analyze
from edge_support.config import Settings, ROOT
from edge_support.inference.output_schema import IncidentRequest
from edge_support.inference.model_client import LocalModelClient, ModelError, messages
from edge_support.services.pipeline import diagnose, cloud_second_opinion, cloud_payload
from edge_support.router.escalation import route_assessment, HARD_REASONS, UNSAFE_ACTION_REASONS

BASE_THRESHOLDS = [0,.4,.6,.7,.8,.9,1]
CHARS_PER_TOKEN = 3.6            # fallback only; normally tokens/char is measured from the local prompts

def quantile(values,q):
    return sorted(values)[max(0,math.ceil(len(values)*q)-1)] if values else None

def wilson(k,n,z=1.96):
    """95% interval for a proportion; honest error bars for small synthetic sets."""
    if not n: return None
    p=k/n; d=1+z*z/n; c=(p+z*z/(2*n))/d; h=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/d
    return [round(max(0,c-h),4),round(min(1,c+h),4)]

def sweep(rows,thresholds,gate_mode=None):
    results=[]
    for threshold in thresholds:
        valid=[r for r in rows if r.get('assessment')]
        routed=[(r,route_assessment(r['assessment'],threshold,gate_mode)) for r in valid]
        accepted=[r for r,route in routed if route['decision']=='LOCAL']
        # Score the same small-tier answer whose routing threshold is being swept.
        wrong=sum((r['assessment'].get('selected') or {}).get('issue_category') != r['expected_category']
                  for r in accepted)
        abstained=len(rows)-len(accepted)
        unsafe_blocks=sum(bool(UNSAFE_ACTION_REASONS.intersection(route['reason_codes'])) for _,route in routed)
        results.append({'threshold':threshold,'incidents':len(rows),'accepted_local':len(accepted),
            'coverage':len(accepted)/len(rows) if rows else None,
            'selective_error':wrong/len(accepted) if accepted else None,
            'selective_error_ci':wilson(wrong,len(accepted)),
            'unsafe_accepts':sum(r['expected_decision']=='ESCALATE' for r in accepted),
            'deferred':abstained,'abstained':abstained,
            'abstention_rate':abstained/len(rows) if rows else None,
            'unsafe_action_blocks':unsafe_blocks,
            'unsafe_action_rate':unsafe_blocks/len(rows) if rows else None})
    return results

def choose(sweeps,target_error):
    """Highest coverage with zero unsafe accepts and selective error <= target; ties -> stricter threshold."""
    best=None
    for mode,curve in sweeps.items():
        for p in curve:
            if not p['accepted_local'] or p['unsafe_accepts'] or (p['selective_error'] or 0)>target_error: continue
            key=(p['coverage'],p['threshold'],mode=='any')
            if best is None or key>best[0]: best=(key,mode,p)
    if best is None:
        return {'threshold':1.01,'gate_mode':'any','coverage':0.0,'selective_error':None,
                'note':'no threshold met the target on this split; everything defers'}
    _,mode,p=best
    return {'threshold':p['threshold'],'gate_mode':mode,'coverage':p['coverage'],'selective_error':p['selective_error'],
            'selective_error_ci':p['selective_error_ci']}

# --- rules-only baseline: thresholds + keywords, no model ("why use an LLM at all?") ---------------
# Generic help-desk vocabulary written from the category names only - deliberately NOT from any split's
# phrasings, so the baseline is not tuned to the test set. First matching category wins, like a naive router.
KEYWORDS={"cpu_saturation":["cpu","processor","slow","lag","sluggish","fan"],
          "memory_pressure":["memory","ram","freeze","hang"],
          "disk_pressure":["disk","storage","space","drive"],
          "thermal_throttling":["hot","heat","overheat","temperature"],
          "battery_degradation":["battery","charge","charger"],
          "wifi_connectivity":["wi-fi","wifi","wireless","signal"],
          "application_crash":["crash","error"],
          "startup":["boot","startup","login"],
          "dns_network":["dns","resolve","hostname","website"]}

def rules_category(case,settings):
    inc=case['incident'];tel=inc.get('telemetry') or {}
    metrics={k:v for k,v in tel.items() if k in Telemetry.model_fields}
    signals=[s['category'] for s in analyze(Telemetry.model_validate(metrics),settings.thresholds)]
    if (tel.get('network') or {}).get('dns_ok') is False: signals.append('dns_network')
    text=(inc.get('description','')+' '+inc.get('logs','')).lower()
    hits=[c for c,words in KEYWORDS.items() if any(w in text for w in words)]
    if signals:
        return next((c for c in signals if c in hits),signals[0])
    return hits[0] if hits else 'unsupported'

# --- energy -------------------------------------------------------------------------------------
class PowerSampler:
    """GPU board power via nvidia-smi at 1 Hz (reports null where GB10/driver exposes no power.draw)."""
    def __init__(self): self.samples=[];self._stop=threading.Event();self.on=bool(shutil.which('nvidia-smi'))
    def __enter__(self):
        self.t0=time.perf_counter()
        if self.on: threading.Thread(target=self._loop,daemon=True).start()
        return self
    def _loop(self):
        while not self._stop.is_set():
            try:
                out=subprocess.run(['nvidia-smi','--query-gpu=power.draw','--format=csv,noheader,nounits'],
                                   capture_output=True,text=True,timeout=3).stdout.strip().splitlines()
                self.samples.append(float(out[0]))
            except (ValueError,IndexError,OSError,subprocess.SubprocessError): pass
            self._stop.wait(1)
    def __exit__(self,*exc): self._stop.set();self.seconds=time.perf_counter()-self.t0
    def summary(self,n):
        if not self.samples: return None
        w=statistics.mean(self.samples)
        return {'avg_gpu_w':round(w,1),'seconds':round(self.seconds,1),'joules_per_incident':round(w*self.seconds/max(1,n),1),
                'samples':len(self.samples),'boundary':'GPU board power from nvidia-smi; excludes CPU/system, no idle subtraction'}

# --- per-case ---------------------------------------------------------------------------------
def incident(case):
    data=dict(case['incident'])
    data['complaint']=data.pop('description')
    return IncidentRequest.model_validate(data)

def leaked(obj,values):
    text=json.dumps(obj)
    return [v for v in values if v and (v in text or json.dumps(v)[1:-1] in text)]

def run_case(case,settings):
    try:
        r=diagnose(incident(case),settings)
    except (ModelError,ValueError):
        return {'id':case['id'],'ok':False,'kind':case.get('kind'),'expected_category':case['expected_category'],
                'expected_decision':case['expected_decision'],'error':'Local inference or input failed',
                'abstained':True,'unsafe_action_blocked':False,
                'rules_category_correct':rules_category(case,settings)==case['expected_category']}
    a=r['tiers'][0]['assessment']
    reqs=r['metrics']['requests']
    # batched usage covers all n choices and is copied onto each sample: count it once
    completion=sum(m['completion_tokens']/(m.get('batched_samples') or 1) for m in reqs if isinstance(m.get('completion_tokens'),int))
    prompt=next((m['prompt_tokens'] for m in reqs if isinstance(m.get('prompt_tokens'),int)),None)
    chars=lambda msgs:sum(len(m['content']) for m in msgs)
    local_msgs=messages(r['ticket']['payload'],settings,settings.batch_samples or settings.strict_schema)
    only_msgs=messages(r['ticket']['payload'],settings,settings.strict_schema)   # a cloud-only design, same prompt path
    hyb_msgs=messages(cloud_payload(r),settings,settings.strict_schema)          # what an approved escalation sends
    hard=bool(HARD_REASONS.intersection(r['route']['reason_codes']))
    return {'id':case['id'],'ok':True,'kind':case.get('kind'),'expected_category':case['expected_category'],
        'expected_decision':case['expected_decision'],'predicted_category':r['diagnosis']['issue_category'],
        'category_correct':r['diagnosis']['issue_category']==case['expected_category'],
        'route_correct':r['route']['decision']==case['expected_decision'],
        'action_correct':r['diagnosis']['recommended_action']==case['expected_action'] if 'expected_action' in case else None,
        'resolved_by':r['tiers'][-1]['tier'],'assessment':a,'route':r['route'],'metrics':r['metrics'],
        'abstained':bool(r['route'].get('abstained')),
        'unsafe_action_blocked':bool(r['metrics'].get('unsafe_action_blocked')),
        'cloud_bound':r['route']['decision']=='ESCALATE' and not hard,'human_handoff':hard,
        'local_prompt_chars':chars(local_msgs),'cloud_only_chars':chars(only_msgs),'hybrid_chars':chars(hyb_msgs),
        'cloud_only_bytes':len(json.dumps(only_msgs)),'hybrid_bytes':len(json.dumps(hyb_msgs)),
        'prompt_tokens':prompt,'completion_tokens':round(completion,1) if completion else None,
        'schema_fallback':any(m.get('schema_enforced') is False for m in reqs),
        'truncated':r['metrics'].get('truncated_samples',0),
        'pii_planted':len(case.get('pii') or []),'pii_leaked':leaked(r,case.get('pii') or []),
        'rules_category_correct':rules_category(case,settings)==case['expected_category'],
        '_result':r}

def rate(rows,key):
    vals=[r.get(key) for r in rows]
    return sum(bool(v) for v in vals)/len(rows) if rows else None

def by_kind(rows):
    groups=defaultdict(list)
    for r in rows: groups[r.get('kind') or 'unlabeled'].append(r)
    return {k:{'n':len(v),'category_accuracy':rate(v,'category_correct'),'route_accuracy':rate(v,'route_correct'),
               'local_rate':sum(r.get('route',{}).get('decision')=='LOCAL' for r in v)/len(v),
               'abstention_rate':rate(v,'abstained'),
               'unsafe_action_block_rate':rate(v,'unsafe_action_blocked'),
               'rules_category_accuracy':rate(v,'rules_category_correct')} for k,v in sorted(groups.items())}

def cost(tokens_in,tokens_out,s):
    if s.cloud_price_in_per_mtok is None or s.cloud_price_out_per_mtok is None: return None
    return (tokens_in*s.cloud_price_in_per_mtok+tokens_out*s.cloud_price_out_per_mtok)/1e6

def main():
    parser=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--simulate',action='store_true')
    parser.add_argument('--samples',type=int,choices=[1,3,5],default=3)
    parser.add_argument('--dataset',default=str(ROOT/'data/evaluation.json'))
    parser.add_argument('--output',default='reports/integrated-benchmark.json')
    parser.add_argument('--threshold',type=float,default=None,help='agreement threshold (default: .env / 0.8)')
    parser.add_argument('--threshold-file',help='use a threshold + gate mode locked by --calibrate')
    parser.add_argument('--calibrate',action='store_true',help='choose threshold + gate mode on THIS split and save it')
    parser.add_argument('--threshold-out',default='reports/threshold.json')
    parser.add_argument('--target-error',type=float,default=.05,help='max category error among locally accepted tickets')
    parser.add_argument('--warmup',action='store_true')
    parser.add_argument('--large',action='store_true',help='keep the second local tier enabled (measures the full ladder)')
    parser.add_argument('--limit',type=int,help='only the first N cases (quick pass)')
    parser.add_argument('--workers',type=int,default=1,help='concurrent tickets (vLLM batches them); 1 = original sequential')
    parser.add_argument('--label',default='',help='free-text run label shown in comparisons')
    parser.add_argument('--cloud-baseline',action='store_true',help='ALSO send every ticket to the configured cloud (costs money)')
    parser.add_argument('--cloud-escalations',action='store_true',help='ALSO send cloud-bound escalations to the cloud (costs money)')
    args=parser.parse_args()
    env=Settings.from_env()
    locked=json.loads(Path(args.threshold_file).read_text()) if args.threshold_file else None
    threshold=args.threshold if args.threshold is not None else (locked['threshold'] if locked else env.agreement_threshold)
    if not 0<=threshold<=1.01: parser.error('threshold must be in [0,1]')
    settings=env.model_copy(update={'simulation_mode':args.simulate,'sample_count':args.samples,
        'agreement_threshold':threshold,'enable_cloud':False,'enable_large_local':args.large and env.enable_large_local,
        **({'gate_mode':locked['gate_mode']} if locked else {})})
    if locked and (locked.get('sample_count'),locked.get('model'))!=(args.samples,settings.local_llm_model if not args.simulate else 'fixture'):
        print(f"warning: threshold file was calibrated for samples={locked.get('sample_count')} model={locked.get('model')}",file=sys.stderr)
    text=Path(args.dataset).read_text()
    cases=json.loads(text) if args.dataset.endswith('.json') else [json.loads(l) for l in text.splitlines() if l.strip()]
    cases=cases[:args.limit]
    if not cases: parser.error('dataset must contain cases')
    if args.calibrate and Path(args.dataset).name.startswith(('test','train')):
        parser.error('calibrate on the calib split; never on train (fine-tuning) or test (held out)')
    if args.warmup: diagnose(incident(cases[0]),settings)
    with PowerSampler() as power:
        if args.workers>1:
            with ThreadPoolExecutor(args.workers) as ex: rows=list(ex.map(lambda c:run_case(c,settings),cases))
        else:
            rows=[run_case(c,settings) for c in cases]
    good=[r for r in rows if r['ok']]
    latency=[r['metrics']['latency_ms'] for r in good]
    n=len(rows)
    # exact fractions (2/3, not 0.6667) so "2 of 3 agree" is its own operating point
    grid=sorted({round(t,9):t for t in BASE_THRESHOLDS+[i/args.samples for i in range(args.samples+1)]}.values())
    sweeps={mode:sweep(rows,grid,mode) for mode in ('any','majority')}
    # --- cloud arms (explicit flags only) ---
    cloud_cfg=env.model_copy(update={'sample_count':args.samples})
    cloud_baseline=hybrid_cloud=None
    if (args.cloud_baseline or args.cloud_escalations) and not (env.enable_cloud and env.cloud_llm_model and not args.simulate):
        parser.error('cloud arms need ENABLE_CLOUD=true and a configured cloud endpoint (and no --simulate)')
    if args.cloud_baseline:
        client=LocalModelClient(cloud_cfg);out=[]
        for r in good:
            try:
                d,m=client.sample(r['_result']['ticket']['payload'],'cloud',0)
                out.append({'correct':bool(d and d.issue_category==r['expected_category']),'latency_ms':m['latency_ms'],
                            'in':m.get('prompt_tokens') or 0,'out':m.get('completion_tokens') or 0})
            except ModelError: out.append({'correct':False,'error':True,'in':0,'out':0})
        tin,tout=sum(o['in'] for o in out),sum(o['out'] for o in out)
        cloud_baseline={'measured':True,'n':len(out),'category_accuracy':rate(out,'correct'),
            'errors':sum(1 for o in out if o.get('error')),'p50_ms':quantile([o['latency_ms'] for o in out if 'latency_ms' in o],.5),
            'input_tokens':tin,'output_tokens':tout,'cost_per_1k':(cost(tin,tout,env)*1000/len(out)) if out and cost(tin,tout,env) is not None else None}
    if args.cloud_escalations:
        for r in good:
            if r['cloud_bound']:
                try:
                    c=cloud_second_opinion(r['_result'],cloud_cfg,True)
                    r['cloud_correct']=bool(c.get('cloud_diagnosis') and c['cloud_diagnosis']['issue_category']==r['expected_category'])
                    r['cloud_tokens']=(c['metrics'].get('prompt_tokens') or 0,c['metrics'].get('completion_tokens') or 0)
                except ModelError: r['cloud_correct']=False;r['cloud_tokens']=(0,0)
        final=[(r['cloud_correct'] if r.get('cloud_bound') else r['category_correct']) for r in good]
        tin=sum(r.get('cloud_tokens',(0,0))[0] for r in good);tout=sum(r.get('cloud_tokens',(0,0))[1] for r in good)
        hybrid_cloud={'measured':True,'escalated':sum(r['cloud_bound'] for r in good),'hybrid_category_accuracy':sum(final)/n,
            'cloud_accuracy_on_escalated':rate([r for r in good if r['cloud_bound']],'cloud_correct'),
            'input_tokens':tin,'output_tokens':tout,'cost_per_1k':(cost(tin,tout,env)*1000/n) if cost(tin,tout,env) is not None else None}
    # --- egress + estimated cost (always; measured arms above override) ---
    measured=[r for r in good if r.get('prompt_tokens')]
    tok_per_char=(sum(r['prompt_tokens'] for r in measured)/sum(r['local_prompt_chars'] for r in measured)) if measured else 1/CHARS_PER_TOKEN
    ctoks=[r['completion_tokens']/args.samples for r in good if r.get('completion_tokens')]
    out_tok=statistics.mean(ctoks) if ctoks else 400
    cloud_bound=[r for r in good if r['cloud_bound']]
    only_in=sum(r['cloud_only_chars'] for r in good)*tok_per_char;only_out=out_tok*len(good)
    hyb_in=sum(r['hybrid_chars'] for r in cloud_bound)*tok_per_char;hyb_out=out_tok*len(cloud_bound)
    est=lambda i,o,k:(cost(i,o,env)*1000/k) if k and cost(i,o,env) is not None else None
    egress={'cloud_only_bytes_per_ticket':round(statistics.mean(r['cloud_only_bytes'] for r in good),1) if good else None,
            'hybrid_bytes_per_ticket':round(sum(r['hybrid_bytes'] for r in cloud_bound)/n,1),
            'hybrid_bytes_per_escalation':round(statistics.mean(r['hybrid_bytes'] for r in cloud_bound),1) if cloud_bound else None,
            'cloud_bound_share':len(cloud_bound)/n,'human_handoff_share':sum(r.get('human_handoff',False) for r in good)/n,
            'basis':'JSON request bodies (system prompt + redacted content); hybrid counts only cloud-bound escalations',
            'raw_telemetry_leaves_site':False}
    cost_est={'estimated':True,'basis':'measured local tokens-per-character applied to each arm\'s prompt text; output = mean local completion per sample',
              'tokens_per_char':round(tok_per_char,4) if measured else None,
              'cloud_only_input_tokens':round(only_in),'hybrid_input_tokens':round(hyb_in),
              'cloud_only_cost_per_1k':est(only_in,only_out,len(good)),'hybrid_cost_per_1k':est(hyb_in,hyb_out,len(good)),
              'prices_per_mtok':[env.cloud_price_in_per_mtok,env.cloud_price_out_per_mtok]}
    planted=sum(r.get('pii_planted',0) for r in good);leaks=[(r['id'],r['pii_leaked']) for r in good if r.get('pii_leaked')]
    confusion=Counter((r['expected_category'],r['predicted_category']) for r in good if not r['category_correct'])
    acc_k=sum(r.get('category_correct',False) for r in rows)
    report={'mode':'SIMULATION_NOT_MODEL_BENCHMARK' if args.simulate else 'LOCAL_MODEL','label':args.label,
        'timestamp_utc':datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'model':settings.local_llm_model if not args.simulate else 'fixture','sample_count':args.samples,
        'threshold':threshold,'gate_mode':settings.gate_mode,'threshold_source':args.threshold_file or ('cli' if args.threshold is not None else 'env'),
        'switches':{k:getattr(settings,k) for k in ('strict_schema','compact_prompt','gate_mode','lenient_parse','retrieval',
                    'local_redaction','batch_samples','max_output_tokens','sample_temperature')},
        'dataset':Path(args.dataset).name,'cases':n,'success_rate':len(good)/n,
        'category_accuracy':acc_k/n,'category_accuracy_ci':wilson(acc_k,n),
        'route_accuracy':sum(r.get('route_correct',False) for r in rows)/n,
        'action_accuracy':(sum(bool(r.get('action_correct')) for r in rows)/n) if any(r.get('action_correct') is not None for r in rows) else None,
        'local_rate':sum(r.get('route',{}).get('decision')=='LOCAL' for r in good)/n,
        'abstentions':sum(bool(r.get('abstained')) for r in rows),
        'abstention_rate':sum(bool(r.get('abstained')) for r in rows)/n,
        'unsafe_action_blocks':sum(bool(r.get('unsafe_action_blocked')) for r in rows),
        'unsafe_action_rate':sum(bool(r.get('unsafe_action_blocked')) for r in rows)/n,
        'resolved_by_large':sum(r.get('resolved_by')=='large' and r['route']['decision']=='LOCAL' for r in good),
        'p50_ms':statistics.median(latency) if latency else None,'p95_ms':quantile(latency,.95),
        'rules_baseline':{'category_accuracy':rate(rows,'rules_category_correct'),'note':'telemetry thresholds + keywords, no model'},
        'by_kind':by_kind(rows),'confusion_top':[{'expected':e,'predicted':p,'count':c} for (e,p),c in confusion.most_common(10)],
        'tokens':{'prompt_mean':round(statistics.mean(r['prompt_tokens'] for r in measured),1) if measured else None,
                  'completion_mean_per_sample':round(statistics.mean(ctoks),1) if ctoks else None,
                  'truncated_samples':sum(r.get('truncated',0) for r in good),
                  'schema_fallback_tickets':sum(1 for r in good if r.get('schema_fallback'))},
        'workers':args.workers,
        'latency_note':'per-ticket wall time' + (f' with {args.workers} tickets in flight (includes queueing)' if args.workers>1 else ' (one ticket at a time)'),
        'privacy':{'pii_planted':planted,'pii_leaked':sum(len(v) for _,v in leaks),'leak_cases':leaks[:10]},
        'egress':egress,'cost_estimate':cost_est,'cloud_baseline':cloud_baseline,'hybrid_cloud':hybrid_cloud,
        'cloud_requests':(cloud_baseline or {}).get('n',0)+(hybrid_cloud or {}).get('escalated',0),
        'energy':power.summary(n),'energy_joules':(power.summary(n) or {}).get('joules_per_incident'),
        'cloud_cost':(hybrid_cloud or {}).get('cost_per_1k'),
        'limitations':'Synthetic team-written data. Small-tier deferral curve; cloud/energy only where measured or labeled estimated.',
        'sweep':sweeps[settings.gate_mode],'sweep_by_mode':sweeps,
        'rows':[{k:v for k,v in r.items() if k!='_result'} for r in rows]}
    if args.calibrate:
        pick=choose(sweeps,args.target_error)
        pick.update({'target_error':args.target_error,'dataset':Path(args.dataset).name,'model':report['model'],
                     'sample_count':args.samples,'switches':report['switches'],'created':report['timestamp_utc']})
        report['calibration']=pick
        out=Path(args.threshold_out);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(pick,indent=2))
        print(f"calibrated: gate_mode={pick['gate_mode']} threshold={pick['threshold']} coverage={pick['coverage']} -> {out}",file=sys.stderr)
    output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,indent=2,default=str))
    with output.with_suffix('.csv').open('w') as f:
        writer=csv.DictWriter(f,fieldnames=['gate_mode']+list(report['sweep'][0]))
        writer.writeheader()
        for mode,curve in sweeps.items(): writer.writerows({'gate_mode':mode,**p} for p in curve)
    print(json.dumps({k:v for k,v in report.items() if k not in {'rows','sweep','sweep_by_mode','by_kind','confusion_top'}},indent=2,default=str))
    if not good: raise SystemExit(1)
if __name__=='__main__': main()
