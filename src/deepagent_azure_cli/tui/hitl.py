"""Human-in-the-loop (HITL) interrupt handling for the Textual TUI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .renderer import format_approval_details


@dataclass(frozen=True, slots=True)
class PendingApproval:
    tool_name: str
    tool_args: dict[str, Any]
    request_count: int


def find_pending_approval(agent: Any, invoke_config: dict[str, Any]) -> PendingApproval | None:
    """Inspect agent state for pending HITL interrupts.

    Returns the first pending approval request found, or None.
    """
    try:
        state = agent.get_state(invoke_config)
    except Exception:
        return None

    tasks = getattr(state, "tasks", None)
    if not tasks:
        return None

    for task in tasks:
        interrupts = getattr(task, "interrupts", None)
        if not interrupts:
            continue

        for interrupt_value in interrupts:
            value = getattr(interrupt_value, "value", interrupt_value)

            action_requests = []
            if isinstance(value, dict):
                action_requests = value.get("action_requests", []) or []

            if not action_requests:
                # Fallback: unknown interrupt payload
                tool_name = "unknown"
                tool_args = value if isinstance(value, dict) else {"value": str(value)}
                return PendingApproval(tool_name=tool_name, tool_args=tool_args, request_count=1)

            first = action_requests[0] if isinstance(action_requests, list) else {}
            tool_name = first.get("name", "unknown") if isinstance(first, dict) else "unknown"
            tool_args = first.get("args", {}) if isinstance(first, dict) else {}
            return PendingApproval(
                tool_name=tool_name,
                tool_args=tool_args if isinstance(tool_args, dict) else {},
                request_count=len(action_requests),
            )

    return None


def build_decisions(approved: bool, request_count: int) -> dict[str, Any]:
    """Mirror one decision per pending request so resume payload shape stays deterministic."""
    if approved:
        decisions = [{"type": "approve"} for _ in range(max(1, request_count))]
    else:
        decisions = [
            {"type": "reject", "message": "User rejected"}
            for _ in range(max(1, request_count))
        ]
    return {"decisions": decisions}


def approval_ui_text(tool_name: str, tool_args: dict[str, Any]) -> tuple[str, str | None]:
    """Return (summary, details) for approval UI display."""
    return format_approval_details(tool_name, tool_args)
