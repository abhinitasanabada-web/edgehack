from __future__ import annotations

from edge_support.inference.output_schema import VerificationResult


def verify(action_id: str, before: dict, after: dict) -> VerificationResult:
    if action_id in {"flush_dns", "restart_dns_client"}:
        before_ok = before.get("network", {}).get("dns_ok")
        after_ok = after.get("network", {}).get("dns_ok")
        return VerificationResult(action_id=action_id, verified=after_ok is True, message=f"DNS before={before_ok}; after={after_ok}", before=before, after=after)
    if action_id == "close_demo_process":
        before_names = {p.get("name", "").lower() for p in before.get("processes", [])}
        after_names = {p.get("name", "").lower() for p in after.get("processes", [])}
        removed = before_names - after_names
        return VerificationResult(action_id=action_id, verified=bool(removed), message=f"Removed processes: {sorted(removed)}", before=before, after=after)
    if action_id == "clear_temp":
        before_bytes = before.get("disk", {}).get("edge_temp_bytes")
        after_bytes = after.get("disk", {}).get("edge_temp_bytes")
        return VerificationResult(action_id=action_id, verified=after_bytes is not None and after_bytes <= (before_bytes or 0), message="Approved temp workspace checked", before=before, after=after)
    return VerificationResult(action_id=action_id, verified=False, message="No verification rule for this action", before=before, after=after)

