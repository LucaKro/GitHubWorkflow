"""
Tests for :mod:`github_workflow.coarse_guard`: when the guard cannot run, every call
that could reach git or GitHub is denied and every other call runs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from basstler_domain_model.locations import PathEnumeration

from github_workflow.coarse_guard import CoarseGuard
from github_workflow.hooks import FileWritingTool, HookInput, HookKey, HookValue

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


def guard(tool: str, tool_input: dict[str, str]) -> CoarseGuard:
    """
    :param tool: The tool called.
    :param tool_input: What it is called with.
    :return: The coarse guard over the call, the guard having failed to start.
    """
    return CoarseGuard(
        HookInput.from_json({HookKey.TOOL_NAME: tool, HookKey.TOOL_INPUT: tool_input}),
        "the runtime could not be installed",
    )


# %% command lines


@pytest.mark.parametrize("command", CoarseGuardDataset.DENIED.lines())
def test_a_command_naming_git_or_github_s_clients_is_denied(command: str):
    output = guard(HookValue.BASH_TOOL, {HookKey.COMMAND: command}).output()

    assert output[HookKey.HOOK_SPECIFIC_OUTPUT][HookKey.PERMISSION_DECISION] == (
        HookValue.DENY
    )


@pytest.mark.parametrize("command", CoarseGuardDataset.ALLOWED.lines())
def test_a_command_naming_none_of_them_runs(command: str):
    assert guard(HookValue.BASH_TOOL, {HookKey.COMMAND: command}).output() is None


def test_a_denial_says_why_the_guard_could_not_run():
    coarse = guard(HookValue.BASH_TOOL, {HookKey.COMMAND: "git status"})

    output = coarse.output()[HookKey.HOOK_SPECIFIC_OUTPUT]

    assert coarse.guard_failure in output[HookKey.PERMISSION_DECISION_REASON]


# %% other tools


@pytest.mark.parametrize("tool", list(FileWritingTool))
def test_a_file_outside_git_s_configuration_may_be_written(tool: FileWritingTool):
    assert guard(tool, {HookKey.FILE_PATH: "/project/src/module.py"}).output() is None


@pytest.mark.parametrize("path", ["/project/.git/hooks/pre-push", "/home/.gitconfig"])
def test_git_s_configuration_may_not_be_written(path: str):
    output = guard(FileWritingTool.EDIT, {HookKey.FILE_PATH: path}).output()

    assert output[HookKey.HOOK_SPECIFIC_OUTPUT][HookKey.PERMISSION_DECISION] == (
        HookValue.DENY
    )


def test_a_github_tool_is_denied_even_when_it_reads():
    output = guard(f"{HookValue.MCP_TOOL_PREFIX}github__get_issue", {}).output()

    assert output[HookKey.HOOK_SPECIFIC_OUTPUT][HookKey.PERMISSION_DECISION] == (
        HookValue.DENY
    )


def test_another_tool_runs():
    assert guard("Read", {HookKey.FILE_PATH: "/project/.git/config"}).output() is None
