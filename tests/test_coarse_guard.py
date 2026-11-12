"""
Tests for :mod:`github_workflow.coarse_guard`: when the guard cannot run, every call
that could reach git or GitHub is denied and every other call runs.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from domain_model.claude_code.hooks import (
    FileWritingTool,
    HookKey,
    HookValue,
    ToolCall,
)
from domain_model.locations import PathEnumeration

from github_workflow.coarse_guard import CoarseGuard

# %% the dataset


class CoarseGuardDataset(PathEnumeration):
    """
    The command lines the coarse guard is tried on.
    """

    ALLOWED = Path(__file__).parent / "dataset" / "coarse_guard" / "allowed.sh"
    """
    One command line per line, each let through.
    """

    DENIED = Path(__file__).parent / "dataset" / "coarse_guard" / "denied.sh"
    """
    One command line per line, each denied.
    """

    def lines(self) -> list[str]:
        """:return: Every command line in the file, comments left out."""
        return [
            line
            for line in self.value.read_text().splitlines()
            if line and not line.startswith("#")
        ]


@pytest.fixture
def coarse() -> CoarseGuard:
    """:return: The coarse guard, the guard having failed to start."""
    return CoarseGuard("the runtime could not be installed")


def call(tool: str, tool_input: dict[str, str]) -> ToolCall:
    """
    :param tool: The tool called.
    :param tool_input: What it is called with.
    :return: The call, as the hook reads it.
    """
    return ToolCall.from_json({HookKey.TOOL_NAME: tool, HookKey.TOOL_INPUT: tool_input})


# %% command lines


@pytest.mark.parametrize("command", CoarseGuardDataset.DENIED.lines())
def test_a_command_naming_git_or_github_s_clients_is_denied(
    command: str, coarse: CoarseGuard
) -> None:
    output = coarse.output(call(HookValue.BASH_TOOL, {HookKey.COMMAND: command}))

    assert output[HookKey.HOOK_SPECIFIC_OUTPUT][HookKey.PERMISSION_DECISION] == (
        HookValue.DENY
    )


@pytest.mark.parametrize("command", CoarseGuardDataset.ALLOWED.lines())
def test_a_command_naming_none_of_them_runs(command: str, coarse: CoarseGuard) -> None:
    assert coarse.output(call(HookValue.BASH_TOOL, {HookKey.COMMAND: command})) is None


def test_a_denial_says_why_the_guard_could_not_run(coarse: CoarseGuard) -> None:
    denied = call(HookValue.BASH_TOOL, {HookKey.COMMAND: "git status"})

    output = coarse.output(denied)[HookKey.HOOK_SPECIFIC_OUTPUT]

    assert coarse.guard_failure in output[HookKey.PERMISSION_DECISION_REASON]


# %% other tools


@pytest.mark.parametrize("tool", list(FileWritingTool))
def test_a_file_outside_git_s_configuration_may_be_written(
    tool: FileWritingTool, coarse: CoarseGuard
) -> None:
    assert (
        coarse.output(call(tool, {HookKey.FILE_PATH: "/project/src/module.py"})) is None
    )


@pytest.mark.parametrize("path", ["/project/.git/hooks/pre-push", "/home/.gitconfig"])
def test_git_s_configuration_may_not_be_written(path: str, coarse: CoarseGuard) -> None:
    output = coarse.output(call(FileWritingTool.EDIT, {HookKey.FILE_PATH: path}))

    assert output[HookKey.HOOK_SPECIFIC_OUTPUT][HookKey.PERMISSION_DECISION] == (
        HookValue.DENY
    )


def test_a_github_tool_is_denied_even_when_it_reads(coarse: CoarseGuard) -> None:
    output = coarse.output(call(f"{HookValue.MCP_TOOL_PREFIX}github__get_issue", {}))

    assert output[HookKey.HOOK_SPECIFIC_OUTPUT][HookKey.PERMISSION_DECISION] == (
        HookValue.DENY
    )


def test_another_tool_runs(coarse: CoarseGuard) -> None:
    assert (
        coarse.output(call("Read", {HookKey.FILE_PATH: "/project/.git/config"})) is None
    )
