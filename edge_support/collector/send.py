"""Run on the employee laptop. Sends real telemetry to an explicit private API; no fixes."""
import argparse
import json
import os
import time
import httpx
from edge_support.collector.telemetry import collect_snapshot
from app.services.privacy import sanitize
from edge_support.inference.model_client import validate_endpoint

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--api-url',default='http://127.0.0.1:8503')
    p.add_argument('--complaint',required=True)
    p.add_argument('--count',type=int,default=1)
    p.add_argument('--interval',type=float,default=30)
    args=p.parse_args()
    if not 1<=args.count<=100 or args.interval<5: p.error('count must be 1–100 and interval at least 5 seconds')
    # A local tunnel is required for HTTP. HTTPS may be used on an approved site network.
    validate_endpoint(args.api_url,cloud=args.api_url.startswith('https://'))
    token=os.getenv('EDGE_SUPPORT_ACTION_TOKEN','')
    headers={'Authorization':f'Bearer {token}'} if token else {}
    with httpx.Client(timeout=3300,trust_env=False,follow_redirects=False) as client:
        for i in range(args.count):
            snapshot=collect_snapshot(args.complaint)
            snapshot.pop('complaint',None)
            # API schema accepts bounded extension metadata, including timestamps.
            payload,counts=sanitize({'complaint':args.complaint,'telemetry':snapshot})
            response=client.post(args.api_url.rstrip('/')+'/diagnose',json=payload,headers=headers)
            if not response.is_success: raise SystemExit(f'API returned HTTP {response.status_code}; check server/token')
            result=response.json()
            print(json.dumps({'incident_id':result['incident_id'],'mode':result['processing_location'],
                'route':result['route'],'signals':result['signals'],'client_redactions':counts}))
            if i+1<args.count: time.sleep(args.interval)
if __name__=='__main__': main()
