"""
Tests for :mod:`github_workflow.guard`: every direct write to git or GitHub is denied,
every read is let through, and the hook fails closed.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from basstler_domain_model.locations import PathEnumeration

from github_workflow.environment import WorkflowVariable
from github_workflow.guard import CommandGuard, HookKey, HookValue, ToolGuard

# %% the dataset


class GuardDataset(PathEnumeration):
    """
    The command lines the guard is tried on.
    """

    ALLOWED = Path(__file__).parent / "dataset" / "guard" / "allowed.sh"
    """
    One command line per line, each let through.
    """

    DENIED = Path(__file__).parent / "dataset" / "guard" / "denied.sh"
    """
    One command line per line, each denied.
    """

    HERE_DOCUMENT_AS_DATA = (
        Path(__file__).parent / "dataset" / "guard" / "here_document_as_data.sh"
    )
    """
    A here-document mentioning a push, read by a program that is no shell.
    """

    HERE_DOCUMENT_RUN_BY_A_SHELL = (
        Path(__file__).parent / "dataset" / "guard" / "here_document_run_by_a_shell.sh"
    )
    """
    A here-document holding a push, run by a shell.
    """

    COMMAND_AFTER_HERE_DOCUMENT = (
        Path(__file__).parent / "dataset" / "guard" / "command_after_here_document.sh"
    )
    """
    A push after a here-document has ended.
    """

    HOOK_SCRIPT = Path(__file__).parents[1] / "plugin" / "hooks" / "guard.sh"
    """
    The hook the plugin runs.
    """

    def lines(self) -> list[str]:
        """:return: Every command line in the file, comments left out."""
        return [
            line
            for line in self.value.read_text().splitlines()
            if line and not line.startswith("#")
        ]


def hook_input(command: str) -> dict[str, object]:
    """
    :param command: A Bash command line.
    :return: The hook's input for running it.
    """
    return {
        HookKey.TOOL_NAME: HookValue.BASH_TOOL,
        HookKey.TOOL_INPUT: {HookKey.COMMAND: command},
    }


# %% command lines


@pytest.mark.parametrize("command", GuardDataset.ALLOWED.lines())
def test_a_read_is_let_through(command: str):
    assert CommandGuard().denial(command) is None


@pytest.mark.parametrize("command", GuardDataset.DENIED.lines())
def test_a_write_is_denied(command: str):
    assert CommandGuard().denial(command) is not None


def test_a_here_document_a_program_reads_is_data():
    assert (
        CommandGuard().denial(GuardDataset.HERE_DOCUMENT_AS_DATA.value.read_text())
        is None
    )


@pytest.mark.parametrize(
    "location",
    [
        GuardDataset.HERE_DOCUMENT_RUN_BY_A_SHELL,
        GuardDataset.COMMAND_AFTER_HERE_DOCUMENT,
    ],
    ids=lambda location: location._name_,
)
def test_a_write_around_a_here_document_is_denied(location: GuardDataset):
    assert CommandGuard().denial(location.value.read_text()) is not None


# %% other tools


@pytest.mark.parametrize(
    "tool",
    ["mcp__github__get_file_contents", "mcp__github__list_pull_requests"]
    + ["mcp__github__search_code", "mcp__github__pull_request_read", "Read"],
)
def test_a_reading_tool_is_let_through(tool: str):
    assert ToolGuard({HookKey.TOOL_NAME: tool}).denial() is None


@pytest.mark.parametrize(
    "tool", ["mcp__github__create_pull_request", "mcp__github__merge_pull_request"]
)
def test_a_github_tool_that_writes_is_denied(tool: str):
    assert ToolGuard({HookKey.TOOL_NAME: tool}).denial() is not None


# %% the hook


def run_hook(
    command: str, interpreter: str = sys.executable
) -> subprocess.CompletedProcess[str]:
    """
    :param command: A Bash command line.
    :param interpreter: The interpreter the hook runs the guard with.
    :return: The finished hook.
    """
    return subprocess.run(
        [str(GuardDataset.HOOK_SCRIPT.value)],
        input=json.dumps(hook_input(command)),
        capture_output=True,
        text=True,
        env={WorkflowVariable.PYTHON: interpreter},
    )


def test_the_hook_denies_a_write():
    finished = run_hook(GuardDataset.DENIED.lines()[0])

    output = json.loads(finished.stdout)[HookKey.HOOK_SPECIFIC_OUTPUT]
    assert output[HookKey.PERMISSION_DECISION] == HookValue.DENY


def test_the_hook_says_nothing_about_a_read():
    finished = run_hook(GuardDataset.ALLOWED.lines()[0])

    assert (finished.returncode, finished.stdout) == (0, "")


def test_the_hook_blocks_the_call_when_the_guard_cannot_run():
    finished = run_hook(GuardDataset.ALLOWED.lines()[0], interpreter="/nonexistent")

    assert finished.returncode == 2


def test_the_hook_blocks_the_call_when_the_guard_fails():
    finished = run_hook("git log 'unbalanced")

    assert finished.returncode == 2
