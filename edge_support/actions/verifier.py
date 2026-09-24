from edge_support.inference.output_schema import VerificationResult

def verify(action_id,before,after,target_process=None,action_success=False):
    verified=False
    message="No verified improvement; obtain more evidence or escalate to human support"
    if action_success and action_id in {"flush_dns","restart_dns_client"}:
        verified=(before.get("network") or {}).get("dns_ok") is False and (after.get("network") or {}).get("dns_ok") is True
        message="DNS changed from failed to successful" if verified else message
    elif action_success and action_id=="close_demo_process" and target_process:
        normalize=lambda n:str(n).lower().removesuffix(".exe")
        target=normalize(target_process)
        old={normalize(p.get("name","")) for p in before.get("processes",[])}
        new={normalize(p.get("name","")) for p in after.get("processes",[])}
        verified=target in old and target not in new
        message="Requested process exited; this alone does not prove memory pressure was resolved" if verified else message
    elif action_success and action_id=="clear_temp":
        old=(before.get("disk") or {}).get("edge_temp_bytes")
        new=(after.get("disk") or {}).get("edge_temp_bytes")
        verified=type(old) in (int,float) and type(new) in (int,float) and 0<=new<old
        message="Approved temporary workspace shrank" if verified else message
    return VerificationResult(action_id=action_id,verified=verified,message=message,before=before,after=after)
