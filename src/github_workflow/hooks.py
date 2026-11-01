"""
What Claude Code hands the workflow's hooks and what they answer, and the answer of the
session start.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum

# %% vocabulary


class HookKey(StrEnum):
    """
    The keys of a hook's input and output.
    """

    TOOL_NAME = "tool_name"
    TOOL_INPUT = "tool_input"
    COMMAND = "command"
    HOOK_SPECIFIC_OUTPUT = "hookSpecificOutput"
    HOOK_EVENT_NAME = "hookEventName"
    PERMISSION_DECISION = "permissionDecision"
    PERMISSION_DECISION_REASON = "permissionDecisionReason"
    SYSTEM_MESSAGE = "systemMessage"
    """
    What the person running Claude Code is shown.
    """

    ADDITIONAL_CONTEXT = "additionalContext"
    """
    What the model is given.
    """


class HookValue(StrEnum):
    """
    The fixed values a hook's input and output carry.
    """

    BASH_TOOL = "Bash"
    """
    The tool running shell commands.
    """

    MCP_TOOL_PREFIX = "mcp__"
    """
    How every MCP tool's name starts.
    """

    PRE_TOOL_USE = "PreToolUse"
    """
    The hook event the guard answers.
    """

    SESSION_START = "SessionStart"
    """
    The hook event the session start answers.
    """

    DENY = "deny"
    """
    The decision denying a call.
    """


# %% the session start's answer


@dataclass(frozen=True)
class SessionStartReport:
    """
    What a session starts with, shown to the person and given to the model alike.
    """

    lines: list[str]
    """
    One line per thing to report.
    """

    def json(self) -> str:
        """:return: The hook's output."""
        text = "\n".join(self.lines)
        return json.dumps(
            {
                HookKey.SYSTEM_MESSAGE: text,
                HookKey.HOOK_SPECIFIC_OUTPUT: {
                    HookKey.HOOK_EVENT_NAME: HookValue.SESSION_START,
                    HookKey.ADDITIONAL_CONTEXT: text,
                },
            }
        )
