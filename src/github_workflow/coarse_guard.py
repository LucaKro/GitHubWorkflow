"""
The guard's stand-in for when the guard itself cannot run - its runtime missing, or the
guard failing: it denies every call that could reach git or GitHub, and lets every other
call run, so a broken runtime does not stop work that never touches either.

Runs on the standard library and :mod:`github_workflow.hooks` alone, from the plugin's
source, before or without any runtime.

Usage: ``python3 -I -c 'import sys; sys.path.insert(0, sys.argv[1]); from
github_workflow.coarse_guard import main; main(sys.argv[2])' <source> <guard failure>
< hook-input.json``
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePath
from typing import Any

from github_workflow.hooks import FileWritingTool, HookKey, HookValue

# %% what reaches git and GitHub


class Program(StrEnum):
    """
    The programs the guard judges, by their executable's name.
    """

    GIT = "git"
    """
    Git itself.
    """

    GITHUB_CLI = "gh"
    """
    GitHub's command-line client.
    """

    CURL = "curl"
    """
    An HTTP client that could call GitHub's API.
    """

    WGET = "wget"
    """
    Another HTTP client that could call GitHub's API.
    """

    @classmethod
    def named_in(cls, command_line: str) -> bool:
        """
        :param command_line: A Bash command line.
        :return: Whether it names any of the programs as a word of its own.
        """
        names = "|".join(re.escape(program) for program in cls)
        return re.search(rf"\b({names})\b", command_line) is not None


class GitConfigurationLocation(StrEnum):
    """
    The names marking a file git reads its configuration or hooks from, and so runs the
    programs it names.
    """

    REPOSITORY = ".git"
    """
    A repository's own directory, its configuration and hooks among it.
    """

    USER = ".gitconfig"
    """
    The user's configuration file.
    """

    @classmethod
    def holds(cls, path: PurePath) -> bool:
        """
        :param path: A file's path.
        :return: Whether git reads its configuration or hooks from the file.
        """
        return cls.REPOSITORY in path.parts or path.name == cls.USER


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


# %% the coarse guard


@dataclass(frozen=True)
class CoarseGuard:
    """
    The decision over one tool call while the guard cannot run.
    """

    hook_input: dict[str, Any]
    """
    The hook's input, as Claude Code sends it.
    """

    guard_failure: str
    """
    Why the guard could not run, as the denial names it.
    """

    def denied_reach(self) -> str | None:
        """
        :return: What the call could reach that the guard would have judged, ``None``
            when it reaches neither git nor GitHub.
        """
        tool = self.hook_input.get(HookKey.TOOL_NAME, "")
        tool_input = self.hook_input.get(HookKey.TOOL_INPUT, {})
        if tool == HookValue.BASH_TOOL:
            if Program.named_in(tool_input[HookKey.COMMAND]):
                return f"a command naming one of {', '.join(Program)}"
            return None
        if tool in FileWritingTool._value2member_map_:
            if GitConfigurationLocation.holds(PurePath(tool_input[HookKey.FILE_PATH])):
                return "a write to git's configuration or hooks"
            return None
        if GitHubTool.names(tool):
            return "a GitHub tool"
        return None

    def output(self) -> dict[str, Any] | None:
        """
        :return: The hook's output denying the call, ``None`` to leave it to the usual
            permissions.
        """
        reach = self.denied_reach()
        if reach is None:
            return None
        return {
            HookKey.HOOK_SPECIFIC_OUTPUT: {
                HookKey.HOOK_EVENT_NAME: HookValue.PRE_TOOL_USE,
                HookKey.PERMISSION_DECISION: HookValue.DENY,
                HookKey.PERMISSION_DECISION_REASON: (
                    f"github-workflow: the guard could not run ({self.guard_failure}), "
                    f"so {reach} is denied until it can; calls reaching neither git "
                    f"nor GitHub still run. Tell the person running the tool."
                ),
            }
        }


# %% entry point


def main(guard_failure: str) -> None:
    """
    Read the hook's input and print the coarse guard's decision.

    :param guard_failure: Why the guard could not run.
    """
    output = CoarseGuard(json.load(sys.stdin), guard_failure).output()
    if output is not None:
        print(json.dumps(output))
