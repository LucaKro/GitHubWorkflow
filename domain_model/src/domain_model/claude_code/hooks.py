"""
What Claude Code hands a hook and what the hook answers: the keys and values of both,
the tool call a PreToolUse hook is asked about, and its answer denying it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Generic, TypeVar

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

Decision = TypeVar("Decision")
"""
What a :class:`ToolCallJudge` decides over a tool call.
"""


@dataclass(frozen=True)
class ToolCall(ABC):
    """
    The tool call a ``PreToolUse`` hook is asked about, of one kind, carrying what that
    kind hands its tool.
    """

    tool: str
    """
    The tool's name.
    """

    @property
    @abstractmethod
    def shown_input(self) -> str:
        """
        :return: What the call hands its tool that tells it apart, as the person is
            shown it.
        """

    @abstractmethod
    def request_decision(self, judge: ToolCallJudge[Decision]) -> Decision:
        """
        :param judge: What decides over tool calls.
        :return: Its decision over this call, by the method for this call's kind.
        """

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> ToolCall:
        """
        :param data: The hook's input, as Claude Code sends it.
        :return: The call it is about.
        """
        tool = data.get(HookKey.TOOL_NAME, "")
        tool_input = data.get(HookKey.TOOL_INPUT, {})
        if tool == HookValue.BASH_TOOL:
            return ShellCommandCall(tool, tool_input.get(HookKey.COMMAND, ""))
        if tool in FileWritingTool:
            return FileWriteCall(tool, tool_input.get(HookKey.FILE_PATH, ""))
        if GitHubTool.names(tool):
            return GitHubToolCall(tool)
        return OtherToolCall(tool)


@dataclass(frozen=True)
class ShellCommandCall(ToolCall):
    """
    A shell command line, run by the Bash tool.
    """

    command: str
    """
    The command line.
    """

    @property
    def shown_input(self) -> str:
        return self.command

    def request_decision(self, judge: ToolCallJudge[Decision]) -> Decision:
        return judge.decide_shell_command(self)


@dataclass(frozen=True)
class FileWriteCall(ToolCall):
    """
    A write of one file.
    """

    file_path: str
    """
    The file written.
    """

    @property
    def shown_input(self) -> str:
        return self.file_path

    def request_decision(self, judge: ToolCallJudge[Decision]) -> Decision:
        return judge.decide_file_write(self)


@dataclass(frozen=True)
class GitHubToolCall(ToolCall):
    """
    A call to an MCP tool reaching GitHub.
    """

    @property
    def tool_without_server(self) -> str:
        """:return: The tool's name, without the MCP server's prefix."""
        return self.tool.rsplit("__", 1)[-1]

    @property
    def shown_input(self) -> str:
        return self.tool

    def request_decision(self, judge: ToolCallJudge[Decision]) -> Decision:
        return judge.decide_github_tool(self)


@dataclass(frozen=True)
class OtherToolCall(ToolCall):
    """
    Any other call, which reaches neither git nor GitHub.
    """

    @property
    def shown_input(self) -> str:
        return self.tool

    def request_decision(self, judge: ToolCallJudge[Decision]) -> Decision:
        return judge.decide_other_tool(self)


@dataclass(frozen=True)
class ToolCallJudge(ABC, Generic[Decision]):
    """
    Decides over a tool call of every kind, one method per kind, so a new kind of call
    is decided by every judge.
    """

    @abstractmethod
    def decide_shell_command(self, call: ShellCommandCall) -> Decision:
        """
        :param call: A shell command line.
        :return: The decision over it.
        """

    @abstractmethod
    def decide_file_write(self, call: FileWriteCall) -> Decision:
        """
        :param call: A write of one file.
        :return: The decision over it.
        """

    @abstractmethod
    def decide_github_tool(self, call: GitHubToolCall) -> Decision:
        """
        :param call: A call to an MCP tool reaching GitHub.
        :return: The decision over it.
        """

    @abstractmethod
    def decide_other_tool(self, call: OtherToolCall) -> Decision:
        """
        :param call: A call reaching neither git nor GitHub.
        :return: The decision over it.
        """


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
