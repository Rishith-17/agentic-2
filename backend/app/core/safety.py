"""Destructive-action confirmation and permission checks.

SECURITY NOTE: user_confirmed must come from the *human* (frontend), never from
the LLM plan. The pipeline strips the LLM's user_confirmed value and only honours
the one supplied directly by the API caller.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

DESTRUCTIVE_SKILLS = frozenset(
    {
        "file_manager",
        "system_control",
        "code_assistant",  # write_file is destructive
    }
)

DESTRUCTIVE_ACTIONS = {
    "file_manager": frozenset({"delete", "rename", "move", "organize_folder"}),
    "system_control": frozenset({"kill_process", "close_application", "terminal_command"}),
    "code_assistant": frozenset({"write_file"}),
}


def requires_confirmation(skill: str, action: str) -> bool:
    """Return True if this skill+action pair needs explicit human confirmation."""
    actions = DESTRUCTIVE_ACTIONS.get(skill)
    if not actions:
        return False
    return action in actions


def build_confirmation_prompt(skill: str, action: str, parameters: dict[str, Any]) -> str:
    """Return a human-readable description of the pending destructive action."""
    detail = ""
    if skill == "file_manager":
        path = parameters.get("path") or parameters.get("target") or ""
        detail = f" on `{path}`" if path else ""
    elif skill == "system_control":
        if action == "kill_process":
            detail = f" PID {parameters.get('pid') or parameters.get('process_name', '')}"
        elif action == "terminal_command":
            detail = f": `{parameters.get('command', '')}`"
        elif action == "close_application":
            detail = f" `{parameters.get('app_name', '')}`"
    elif skill == "code_assistant":
        detail = f" to `{parameters.get('path', '')}`"

    return (
        f"⚠️ Confirmation required: **{skill}.{action}**{detail}. "
        "Send the same request again with `user_confirmed: true` to proceed."
    )


def validate_execution_allowed(
    skill: str,
    action: str,
    parameters: dict[str, Any],
    *,
    user_confirmed: bool,
    require_confirmation: bool,
) -> tuple[bool, str | None]:
    """
    Returns (allowed, message).
    - If require_confirmation is False (env opt-out), always allow.
    - If the action is destructive and user_confirmed is False, block and return prompt.
    - user_confirmed must originate from the API request body, NOT from the LLM plan.
    """
    if not require_confirmation:
        return True, None
    if requires_confirmation(skill, action) and not user_confirmed:
        return False, build_confirmation_prompt(skill, action, parameters)
    return True, None
