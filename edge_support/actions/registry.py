from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ActionSpec:
    action_id: str
    description: str
    requires_confirmation: bool = True
    high_risk: bool = False


ACTION_REGISTRY: dict[str, ActionSpec] = {
    "flush_dns": ActionSpec("flush_dns", "Flush the Windows DNS resolver cache."),
    "restart_dns_client": ActionSpec("restart_dns_client", "Restart the approved Windows DNS Client service.", high_risk=True),
    "close_demo_process": ActionSpec("close_demo_process", "Close a process only when its name is on the demo allowlist."),
    "clear_temp": ActionSpec("clear_temp", "Clear only the EdgeSupport-approved temporary workspace."),
    "collect_more_telemetry": ActionSpec("collect_more_telemetry", "Collect another endpoint snapshot.", requires_confirmation=False),
    "no_action_escalate": ActionSpec("no_action_escalate", "Do not change the endpoint; prepare an escalation.", requires_confirmation=False),
}


def get_action(action_id: str) -> ActionSpec | None:
    return ACTION_REGISTRY.get(action_id)

