"""
What Claude Code hands a hook and what the hook answers: the keys and values of both, the
tool call a PreToolUse hook is asked about, and its answer denying it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

# %% vocabulary


class HookKey(StrEnum):
    """
    The keys of a hook's input and output.
    """

    TOOL_NAME = "tool_name"
    """
    The name of the tool a call is to.
    """

    TOOL_INPUT = "tool_input"
    """
    What the call hands the tool.
    """

    COMMAND = "command"
    """
    The command line a Bash call runs.
    """

    FILE_PATH = "file_path"
    """
    The file a file-writing call writes.
    """

    HOOKS = "hooks"
    """
    The hooks a plugin registers, by event.
    """

    MATCHER = "matcher"
    """
    The tools a registered hook is run for, as a pattern of their names.
    """

    HOOK_SPECIFIC_OUTPUT = "hookSpecificOutput"
    """
    What a hook answers that only its event reads.
    """

    HOOK_EVENT_NAME = "hookEventName"
    """
    The event a hook answers.
    """

    PERMISSION_DECISION = "permissionDecision"
    """
    What the hook decided about a call.
    """

    PERMISSION_DECISION_REASON = "permissionDecisionReason"
    """
    Why, as the model is told.
    """

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
    The hook event before each tool call, which may deny it.
    """

    SESSION_START = "SessionStart"
    """
    The hook event starting a session.
    """

    STOP = "Stop"
    """
    The hook event ending each of the model's turns.
    """

    SESSION_END = "SessionEnd"
    """
    The hook event ending the session.
    """

    USER_PROMPT_SUBMIT = "UserPromptSubmit"
    """
    The hook event on each prompt the person submits.
    """

    DENY = "deny"
    """
    The decision denying a call.
    """


class FileWritingTool(StrEnum):
    """
    The Claude Code tools that write a file, by their names.
    """

    WRITE = "Write"
    """
    Writes a whole file.
    """

    EDIT = "Edit"
    """
    Replaces one part of a file.
    """

    MULTI_EDIT = "MultiEdit"
    """
    Replaces several parts of a file.
    """


class GitHubTool(StrEnum):
    """
    What marks a tool's name as one of an MCP server reaching GitHub.
    """

    NAME_PART = "github"
    """
    The word its name holds, compared in lower case.
    """

    @classmethod
    def names(cls, tool: str) -> bool:
        """
        :param tool: A tool's name.
        :return: Whether it is an MCP tool reaching GitHub.
        """
        return (
            tool.startswith(HookValue.MCP_TOOL_PREFIX)
            and cls.NAME_PART in tool.casefold()
        )


# %% one tool call


class ToolKind(StrEnum):
    """
    The kinds of tool call that can reach git or GitHub, and every other.
    """

    BASH = "bash"
    """
    A shell command line.
    """

    FILE_WRITE = "file write"
    """
    A write of one file.
    """

    GITHUB = "github"
    """
    A call to an MCP tool reaching GitHub.
    """

    OTHER = "other"
    """
    Any other call, which reaches neither git nor GitHub.
    """


@dataclass(frozen=True)
class HookInput:
    """
    The tool call a ``PreToolUse`` hook is asked about.
    """

    tool: str
    """
    The tool's name.
    """

    command: str = ""
    """
    The command line a Bash call runs, empty for any other tool.
    """

    file_path: str = ""
    """
    The file a file-writing call writes, empty for any other tool.
    """

    @property
    def kind(self) -> ToolKind:
        """:return: What kind of call it is."""
        if self.tool == HookValue.BASH_TOOL:
            return ToolKind.BASH
        if self.tool in FileWritingTool:
            return ToolKind.FILE_WRITE
        if GitHubTool.names(self.tool):
            return ToolKind.GITHUB
        return ToolKind.OTHER

    @property
    def tool_without_server(self) -> str:
        """:return: The tool's name, without the MCP server's prefix it may carry."""
        return self.tool.rsplit("__", 1)[-1]

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> HookInput:
        """
        :param data: The hook's input, as Claude Code sends it.
        :return: The call it is about.
        """
        tool_input = data.get(HookKey.TOOL_INPUT, {})
        return cls(
            data.get(HookKey.TOOL_NAME, ""),
            tool_input.get(HookKey.COMMAND, ""),
            tool_input.get(HookKey.FILE_PATH, ""),
        )


@dataclass(frozen=True)
class ToolCallDenial:
    """
    A ``PreToolUse`` hook's answer denying a tool call.
    """

    reason: str
    """
    Why the call is denied, as the model is told.
    """

    shown: str | None = None
    """
    What the person is shown about it, ``None`` for nothing.
    """

    def answer(self) -> dict[str, Any]:
        """:return: The hook's output."""
        answer: dict[str, Any] = {
            HookKey.HOOK_SPECIFIC_OUTPUT: {
                HookKey.HOOK_EVENT_NAME: HookValue.PRE_TOOL_USE,
                HookKey.PERMISSION_DECISION: HookValue.DENY,
                HookKey.PERMISSION_DECISION_REASON: self.reason,
            }
        }
        if self.shown is not None:
            answer[HookKey.SYSTEM_MESSAGE] = self.shown
        return answer
