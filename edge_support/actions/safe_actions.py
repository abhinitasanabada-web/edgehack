from __future__ import annotations

import platform
import subprocess
from pathlib import Path

from edge_support.inference.output_schema import ActionResult


DEMO_PROCESS_ALLOWLIST = {"notepad", "calculatorapp", "mspaint"}


def _run(command: list[str], action_id: str) -> ActionResult:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
        return ActionResult(action_id=action_id, executed=True, success=completed.returncode == 0, message="Command completed" if completed.returncode == 0 else "Command failed", stdout=completed.stdout[-2000:], stderr=completed.stderr[-2000:])
    except (OSError, subprocess.TimeoutExpired) as exc:
        return ActionResult(action_id=action_id, executed=True, success=False, message=str(exc))


def execute_action(action_id: str, context: dict | None = None, dry_run: bool = False) -> ActionResult:
    """Execute only registry-approved actions on the Windows endpoint."""
    context = context or {}
    if action_id in {"collect_more_telemetry", "no_action_escalate"}:
        return ActionResult(action_id=action_id, executed=False, success=True, message="No endpoint change requested")
    if platform.system() != "Windows":
        return ActionResult(action_id=action_id, executed=False, success=False, message="Windows endpoint action refused outside Windows")
    if dry_run:
        return ActionResult(action_id=action_id, executed=False, success=True, message="Dry run: action approved")
    if action_id == "flush_dns":
        return _run(["ipconfig", "/flushdns"], action_id)
    if action_id == "restart_dns_client":
        return _run(["powershell.exe", "-NoProfile", "-Command", "Restart-Service -Name Dnscache"], action_id)
    if action_id == "clear_temp":
        root = Path.home() / "EdgeSupportSafeTemp"
        root.mkdir(exist_ok=True)
        command = f"Remove-Item -LiteralPath '{root}\\*' -Recurse -Force -ErrorAction SilentlyContinue"
        return _run(["powershell.exe", "-NoProfile", "-Command", command], action_id)
    if action_id == "close_demo_process":
        name = str(context.get("process_name", "")).lower().removesuffix(".exe")
        if name not in DEMO_PROCESS_ALLOWLIST:
            return ActionResult(action_id=action_id, executed=False, success=False, message="Process is not on the demo allowlist")
        return _run(["taskkill", "/IM", f"{name}.exe", "/T", "/F"], action_id)
    return ActionResult(action_id=action_id, executed=False, success=False, message="Unknown action ID")

