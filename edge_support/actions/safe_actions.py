"""This Python library is dry-run only. Windows changes require the interactive collector."""
from edge_support.actions.registry import get_action
from edge_support.inference.output_schema import ActionResult

def execute_action(action_id,context=None,dry_run=True):
    action=get_action(action_id)
    return ActionResult(action_id=action_id,executed=False,success=bool(action and dry_run),
        message="Known action, dry-run only; use the Windows collector's per-action confirmation" if action else "Unknown action refused")
