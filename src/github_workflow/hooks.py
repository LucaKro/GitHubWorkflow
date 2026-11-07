"""
What Claude Code hands the workflow's hooks and what they answer, and the answer of the
session start.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

# %% who speaks


class Speaker(StrEnum):
    """
    Who a line shown to the person or given to the model comes from.
    """

    WORKFLOW = "github-workflow"
    """
    The workflow: its commands, hooks and session start.
    """

    def says(self, text: str) -> str:
        """
        :param text: What is said.
        :return: It, opened by who says it.
        """
        return f"{self}: {text}"


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
    What the guard decided about a call.
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


class ToolKind(StrEnum):
    """
    The kinds of tool call the guard judges, and every other.
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


# %% one tool call


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
    """
    What the line says.
    """

    TONE = "tone"
    """
    How it stands out, by the tone's name.
    """

    AUDIENCE = "audience"
    """
    Who it is for.
    """

    EMPHASES = "emphases"
    """
    Its emphasised parts, each with its highlight.
    """


class Audience(StrEnum):
    """
    Who a line the session starts with is for.
    """

    EVERYONE = "everyone"
    """
    The person, who sees it in the terminal, and the model.
    """

    MODEL = "model"
    """
    The model alone, such as an instruction on how to work, which the person need
    not read on every prompt.
    """


class Highlight(StrEnum):
    """
    How a part of a line stands out from the rest, valued as its terminal style; none
    is a colour a :class:`Tone` uses, and each reads on dark and light terminals.
    """

    HEADING = "1;94"
    """
    A section's heading: bold bright blue.
    """

    STATUS = "32"
    """
    A pull request's status tags: green.
    """

    CRITICAL = "1;97;45"
    """
    A critical finding's priority tag: bold white on magenta.
    """

    HIGH = "1;95"
    """
    A high finding's priority tag: bold bright magenta.
    """

    MEDIUM = "95"
    """
    A medium finding's priority tag: bright magenta.
    """

    LOW = "2;95"
    """
    A low finding's priority tag: dim bright magenta.
    """


@dataclass(frozen=True)
class Emphasis:
    """
    A part of a line shown in a style of its own.
    """

    part: str
    """
    The part, as it stands in the line's text; its first occurrence is styled.
    """

    highlight: Highlight
    """
    How it stands out.
    """


@dataclass(frozen=True)
class NumberLink:
    """
    A pull request or issue named by its number, as a Markdown link to its page.
    """

    number: int
    """
    Its number.
    """

    url: str
    """
    Its page on GitHub.
    """

    def markdown(self) -> str:
        """:return: The link, ``[#<number>](<url>)``."""
        return f"[#{self.number}]({self.url})"


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

    audience: Audience = Audience.EVERYONE
    """
    Who it is for.
    """

    emphases: tuple[Emphasis, ...] = ()
    """
    The parts of it shown in styles of their own.
    """

    @property
    def shown(self) -> str:
        """
        :return: The line in bold, in its tone's colour, its emphasised parts in their
            own styles, as the person sees it.
        """
        line = f"\033[1;{self.tone}m"
        text = self.text
        for emphasis in self.emphases:
            before, found, text = text.partition(emphasis.part)
            line += before
            if found:
                line += f"\033[0;{emphasis.highlight}m{found}\033[0;1;{self.tone}m"
        return f"{line}{text}\033[0m"

    def to_json(self) -> str:
        """:return: The line, for a process that reports to the session start."""
        return json.dumps(
            {
                ReportLineKey.TEXT: self.text,
                ReportLineKey.TONE: self.tone.name,
                ReportLineKey.AUDIENCE: self.audience,
                ReportLineKey.EMPHASES: [
                    [emphasis.part, emphasis.highlight] for emphasis in self.emphases
                ],
            }
        )

    @classmethod
    def from_json(cls, line: str) -> ReportLine:
        """
        :param line: A line as :meth:`to_json` wrote it.
        :return: The line.
        """
        data = json.loads(line)
        return cls(
            data[ReportLineKey.TEXT],
            Tone[data[ReportLineKey.TONE]],
            Audience(data[ReportLineKey.AUDIENCE]),
            tuple(
                Emphasis(part, Highlight(highlight))
                for part, highlight in data[ReportLineKey.EMPHASES]
            ),
        )


@dataclass(frozen=True)
class SessionStartReport:
    """
    What a session starts with: coloured for the person, the lines for everyone only,
    and plain for the model, every line.
    """

    lines: list[ReportLine]
    """
    One line per thing to report.
    """

    event: HookValue = HookValue.SESSION_START
    """
    The hook event the report answers.
    """

    def to_json(self) -> str:
        """:return: The hook's output."""
        return json.dumps(
            {
                HookKey.SYSTEM_MESSAGE: "\n".join(
                    line.shown
                    for line in self.lines
                    if line.audience is Audience.EVERYONE
                ),
                HookKey.HOOK_SPECIFIC_OUTPUT: {
                    HookKey.HOOK_EVENT_NAME: self.event,
                    HookKey.ADDITIONAL_CONTEXT: "\n".join(
                        line.text for line in self.lines
                    ),
                },
            }
        )
