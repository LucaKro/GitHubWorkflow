"""
Tests for :mod:`github_workflow.guard`: every direct write to git or GitHub is denied,
every read is let through, and the hook fails closed.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from basstler_domain_model.locations import PathEnumeration

from github_workflow.environment import WorkflowVariable
from github_workflow.guard import (
    CommandGuard,
    DescriptionRewriting,
    GitWrite,
    PullRequestOpening,
    ToolGuard,
)
from github_workflow.hooks import FileWritingTool, HookKey, HookValue

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

    NEEDS_GO_AHEAD = Path(__file__).parent / "dataset" / "guard" / "needs_go_ahead.sh"
    """
    One workflow command line per line, each confirmed by the person before it runs.
    """

    WITHOUT_GO_AHEAD = (
        Path(__file__).parent / "dataset" / "guard" / "without_go_ahead.sh"
    )
    """
    One workflow command line per line, each run without asking.
    """

    HOOK_SCRIPT = Path(__file__).parents[1] / "hooks" / "guard.sh"
    """
    The hook the plugin runs.
    """

    HOOK_CONFIGURATION = Path(__file__).parents[1] / "hooks" / "hooks.json"
    """
    Which hook the plugin runs for which tool.
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


# %% what to do instead


@pytest.mark.parametrize("write", list(GitWrite))
def test_a_git_write_names_the_workflow_command_doing_its_job(write: GitWrite):
    denial = CommandGuard().denial(f"git {write} feature")

    assert denial is not None
    assert denial.instead == write.instead


def test_opening_a_pull_request_names_the_workflow_s_draft():
    denial = CommandGuard().denial("gh pr create --title Change")

    assert denial is not None
    assert denial.instead == PullRequestOpening.instead


def test_editing_a_pull_request_names_the_workflow_s_describe():
    denial = CommandGuard().denial("gh pr edit 9 --body-file description.md")

    assert denial is not None
    assert denial.instead == DescriptionRewriting.instead


def test_a_write_no_workflow_command_does_names_none():
    denial = CommandGuard().denial("gh pr merge 9")

    assert denial is not None
    assert denial.instead is None


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


def test_the_github_tool_opening_a_pull_request_names_the_workflow_s_draft():
    tool = f"mcp__github__{PullRequestOpening.TOOL}"

    denial = ToolGuard({HookKey.TOOL_NAME: tool}).denial()

    assert denial is not None
    assert denial.instead == PullRequestOpening.instead


# %% the person's go-ahead


@pytest.mark.parametrize("command", GuardDataset.NEEDS_GO_AHEAD.lines())
def test_a_workflow_command_needing_the_person_s_go_ahead_is_asked_about(command: str):
    output = ToolGuard(hook_input(command)).output()[HookKey.HOOK_SPECIFIC_OUTPUT]

    assert output[HookKey.PERMISSION_DECISION] == HookValue.ASK


@pytest.mark.parametrize("command", GuardDataset.WITHOUT_GO_AHEAD.lines())
def test_a_workflow_command_the_agent_may_run_alone_is_not_asked_about(command: str):
    assert ToolGuard(hook_input(command)).output() is None


def test_a_denial_outweighs_asking():
    command = f"{GuardDataset.NEEDS_GO_AHEAD.lines()[0]} && git push"

    output = ToolGuard(hook_input(command)).output()[HookKey.HOOK_SPECIFIC_OUTPUT]

    assert output[HookKey.PERMISSION_DECISION] == HookValue.DENY


# %% files git runs programs from


@pytest.mark.parametrize("tool", list(FileWritingTool))
@pytest.mark.parametrize(
    "path", ["/checkout/.git/config", ".git/hooks/pre-push", "/checkout/.gitconfig"]
)
def test_writing_a_file_git_runs_programs_from_is_denied(
    tool: FileWritingTool, path: str
):
    hook_input = {
        HookKey.TOOL_NAME: tool,
        HookKey.TOOL_INPUT: {HookKey.FILE_PATH: path},
    }

    assert ToolGuard(hook_input).denial() is not None


@pytest.mark.parametrize("path", ["/checkout/src/module.py", "/checkout/.gitignore"])
def test_writing_another_file_is_let_through(path: str):
    hook_input = {
        HookKey.TOOL_NAME: FileWritingTool.WRITE,
        HookKey.TOOL_INPUT: {HookKey.FILE_PATH: path},
    }

    assert ToolGuard(hook_input).denial() is None


@pytest.mark.parametrize("tool", list(FileWritingTool))
def test_the_hook_runs_for_the_tools_writing_files(tool: FileWritingTool):
    configuration = json.loads(GuardDataset.HOOK_CONFIGURATION.value.read_text())
    [guard] = configuration[HookKey.HOOKS][HookValue.PRE_TOOL_USE]

    assert re.fullmatch(guard[HookKey.MATCHER], tool)


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


def test_the_hook_denies_a_write_and_says_what_to_run_instead():
    command = GuardDataset.DENIED.lines()[0]

    finished = run_hook(command)

    output = json.loads(finished.stdout)[HookKey.HOOK_SPECIFIC_OUTPUT]
    assert output[HookKey.PERMISSION_DECISION] == HookValue.DENY
    assert (
        output[HookKey.PERMISSION_DECISION_REASON]
        == CommandGuard().denial(command).message()
    )


def test_the_hook_says_nothing_about_a_read():
    finished = run_hook(GuardDataset.ALLOWED.lines()[0])

    assert (finished.returncode, finished.stdout) == (0, "")


def test_the_hook_blocks_the_call_when_the_guard_cannot_run():
    finished = run_hook(GuardDataset.ALLOWED.lines()[0], interpreter="/nonexistent")

    assert finished.returncode == 2


def test_the_hook_installs_a_missing_runtime_and_blocks_when_that_fails(
    tmp_path: Path,
):
    """
    A plugin without the installer stands in for an install that fails, so nothing is
    downloaded.
    """
    finished = subprocess.run(
        [str(GuardDataset.HOOK_SCRIPT.value)],
        input=json.dumps(hook_input(GuardDataset.ALLOWED.lines()[0])),
        capture_output=True,
        text=True,
        env={
            "HOME": str(tmp_path / "home"),
            "PATH": os.environ["PATH"],
            "CLAUDE_PLUGIN_ROOT": str(tmp_path / "plugin"),
        },
    )

    assert finished.returncode == 2
    assert "could not install the runtime" in finished.stderr


def test_the_hook_blocks_the_call_when_the_guard_fails():
    finished = run_hook("git log 'unbalanced")

    assert finished.returncode == 2
