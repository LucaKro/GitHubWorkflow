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
    FILE_PATH = "file_path"
    HOOKS = "hooks"
    MATCHER = "matcher"
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

    STOP = "Stop"
    """
    The hook event ending each of the model's turns, which saves unsaved notes.
    """

    SESSION_END = "SessionEnd"
    """
    The hook event ending the session, which saves unsaved notes too.
    """

    USER_PROMPT_SUBMIT = "UserPromptSubmit"
    """
    The hook event the session start answers instead, on the first prompt, when the
    plugin arrived too late for the session's start.
    """

    DENY = "deny"
    """
    The decision denying a call.
    """

    ASK = "ask"
    """
    The decision having the person confirm a call before it runs.
    """


class FileWritingTool(StrEnum):
    """
    The Claude Code tools that write a file, by their names.
    """

    WRITE = "Write"
    EDIT = "Edit"
    MULTI_EDIT = "MultiEdit"


# %% the session start's answer


class Tone(StrEnum):
    """
    How a line of the session start stands out, named for what it means, valued as the
    terminal colour it is shown in.
    """

    NEWS = "36"
    """
    What was loaded or done: cyan.
    """

    ACTION = "33"
    """
    Something for the person to do: yellow.
    """

    PROBLEM = "31"
    """
    Something that failed: red.
    """


class ReportLineKey(StrEnum):
    """
    The keys of a report line handed from one process to another.
    """

    TEXT = "text"
    TONE = "tone"


@dataclass(frozen=True)
class ReportLine:
    """
    One line the session starts with.
    """

    text: str
    """
    What it says.
    """

    tone: Tone
    """
    How it stands out.
    """

    @property
    def shown(self) -> str:
        """:return: The line in bold, in its tone's colour, as the person sees it."""
        return f"\033[1;{self.tone}m{self.text}\033[0m"

    def json(self) -> str:
        """:return: The line, for a process that reports to the session start."""
        return json.dumps(
            {ReportLineKey.TEXT: self.text, ReportLineKey.TONE: self.tone.name}
        )

    @classmethod
    def from_json(cls, line: str) -> ReportLine:
        """
        :param line: A line as :meth:`json` wrote it.
        :return: The line.
        """
        data = json.loads(line)
        return cls(data[ReportLineKey.TEXT], Tone[data[ReportLineKey.TONE]])


@dataclass(frozen=True)
class SessionStartReport:
    """
    What a session starts with: coloured for the person, plain for the model.
    """

    lines: list[ReportLine]
    """
    One line per thing to report.
    """

    event: HookValue = HookValue.SESSION_START
    """
    The hook event the report answers.
    """

    def json(self) -> str:
        """:return: The hook's output."""
        return json.dumps(
            {
                HookKey.SYSTEM_MESSAGE: "\n".join(line.shown for line in self.lines),
                HookKey.HOOK_SPECIFIC_OUTPUT: {
                    HookKey.HOOK_EVENT_NAME: self.event,
                    HookKey.ADDITIONAL_CONTEXT: "\n".join(
                        line.text for line in self.lines
                    ),
                },
            }
        )
