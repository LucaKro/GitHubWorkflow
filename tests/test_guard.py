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

from basstler_domain_model.environment import ClaudeCodeVariable
from basstler_domain_model.locations import PathEnumeration

from github_workflow.environment import WorkflowVariable
import github_workflow
import github_workflow.guard as guard
from github_workflow.guard import (
    SessionVariable,
    CommandGuard,
    CommandLine,
    DescriptionRewriting,
    OwnPullRequestTool,
    GitWrite,
    PullRequestOpening,
    ToolGuard,
)
from github_workflow.command_line import ToolRepository
from github_workflow.hooks import FileWritingTool, HookKey, HookValue

from .test_coarse_guard import CoarseGuardDataset

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
    One command line per line, each a write the guard sees and denies.
    """

    DENIED_UNSEEN = Path(__file__).parent / "dataset" / "guard" / "denied_unseen.sh"
    """
    One command line per line, each denied only because the guard cannot see what it
    runs.
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

    PERSON_ONLY = Path(__file__).parent / "dataset" / "guard" / "person_only.sh"
    """
    One workflow command line per line, each only the person's to run.
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


@pytest.mark.parametrize(
    "command, words",
    [
        ("git branch --show-current 2>&1", ["git", "branch", "--show-current"]),
        ("git log -1 2>/dev/null", ["git", "log", "-1"]),
        ("git branch 2 >out.txt", ["git", "branch", "2"]),
        ('git branch "2">out.txt', ["git", "branch", "2"]),
        (">out.txt git push", ["git", "push"]),
    ],
    ids=["descriptor", "target", "spaced number", "quoted number", "leading"],
)
def test_a_redirection_is_no_word_of_its_command(command: str, words: list[str]):
    assert CommandLine(command).simple_commands() == [words]


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
    assert denial.instead == PullRequestOpening.instead()


def test_editing_a_pull_request_names_the_workflow_s_describe():
    denial = CommandGuard().denial("gh pr edit 9 --body-file description.md")

    assert denial is not None
    assert denial.instead == DescriptionRewriting.instead()


def test_a_write_no_workflow_command_does_names_none():
    denial = CommandGuard().denial("gh pr merge 9")

    assert denial is not None
    assert denial.instead is None


# %% other tools


@pytest.mark.parametrize(
    "tool",
    ["mcp__github__get_file_contents", "mcp__github__list_pull_requests"]
    + ["mcp__github__search_code", "mcp__github__pull_request_read", "Read"]
    + ["mcp__github__actions_list", "mcp__github__actions_get"],
)
def test_a_reading_tool_is_let_through(tool: str):
    assert ToolGuard({HookKey.TOOL_NAME: tool}).denial() is None


@pytest.mark.parametrize(
    "tool",
    ["mcp__github__create_pull_request", "mcp__github__merge_pull_request"]
    + ["mcp__github__issue_write", "mcp__github__actions_run_trigger"],
)
def test_a_github_tool_that_writes_is_denied(tool: str):
    assert ToolGuard({HookKey.TOOL_NAME: tool}).denial() is not None


@pytest.mark.parametrize("tool", list(OwnPullRequestTool))
def test_a_github_tool_labelling_or_answering_reviews_names_the_workflow_s_command(
    tool: OwnPullRequestTool,
):
    denial = ToolGuard({HookKey.TOOL_NAME: f"mcp__github__{tool}"}).denial()

    assert denial.instead == tool.instead()


def test_the_github_tool_opening_a_pull_request_names_the_workflow_s_draft():
    tool = f"mcp__github__{PullRequestOpening.TOOL}"

    denial = ToolGuard({HookKey.TOOL_NAME: tool}).denial()

    assert denial is not None
    assert denial.instead == PullRequestOpening.instead()


def test_every_denial_says_how_to_report_an_unnecessary_one():
    """
    A session blocked by mistake learns where to say so, right where it is blocked.
    """
    command = GuardDataset.DENIED.lines()[0]

    assert ToolRepository.refusal_hint() in CommandGuard().denial(command).message()


def test_every_denial_says_never_to_get_around_it():
    command = GuardDataset.DENIED.lines()[0]

    assert ToolRepository.workaround_ban() in CommandGuard().denial(command).message()


# %% the person's go-ahead


@pytest.mark.parametrize("command", GuardDataset.PERSON_ONLY.lines())
def test_a_command_only_the_person_runs_is_denied_not_asked(command: str):
    """
    Not even the person's go-ahead lets a session run it.
    """
    output = ToolGuard(hook_input(command)).output()[HookKey.HOOK_SPECIFIC_OUTPUT]

    assert output[HookKey.PERMISSION_DECISION] == HookValue.DENY


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


# %% denials the person is shown


@pytest.mark.parametrize("command", GuardDataset.DENIED_UNSEEN.lines())
def test_a_command_denied_unseen_is_shown_to_the_person(command: str):
    """
    The person judges how often the guard denies what it cannot see into, and so whether
    that rule is worth its cost.
    """
    output = ToolGuard(hook_input(command)).output()

    assert output[HookKey.HOOK_SPECIFIC_OUTPUT][HookKey.PERMISSION_DECISION] == (
        HookValue.DENY
    )
    assert command in output[HookKey.SYSTEM_MESSAGE]


@pytest.mark.parametrize("command", GuardDataset.DENIED.lines())
def test_a_write_the_guard_saw_is_not_shown_to_the_person(command: str):
    output = ToolGuard(hook_input(command)).output()

    assert HookKey.SYSTEM_MESSAGE not in output


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


def test_the_hook_lets_a_read_through_when_the_runtime_cannot_run():
    """
    The guard runs from the plugin's source instead, judging the call as usual.
    """
    finished = run_hook(GuardDataset.ALLOWED.lines()[0], interpreter="/nonexistent")

    assert (finished.returncode, finished.stdout) == (0, "")


def test_the_hook_denies_a_write_when_the_runtime_cannot_run():
    finished = run_hook(GuardDataset.DENIED.lines()[0], interpreter="/nonexistent")

    output = json.loads(finished.stdout)[HookKey.HOOK_SPECIFIC_OUTPUT]
    assert output[HookKey.PERMISSION_DECISION] == HookValue.DENY


def test_the_guard_runs_on_the_standard_library_alone():
    """
    Without site-packages, only the standard library and the plugin's source can be
    imported.
    """
    source = Path(github_workflow.__file__).parents[1]
    imported = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-c",
            f"import sys; sys.path.insert(0, {str(source)!r}); import {guard.__name__}",
        ],
        capture_output=True,
        text=True,
    )

    assert (imported.returncode, imported.stderr) == (0, "")


def test_the_guard_names_the_session_variable_as_the_domain_model_does():
    assert SessionVariable.COMMAND_MARKER == ClaudeCodeVariable.COMMAND_MARKER


def test_the_hook_lets_other_work_run_when_the_guard_cannot_run():
    """
    A broken runtime stops only what could reach git or GitHub, not every command.
    """
    finished = run_hook(
        CoarseGuardDataset.ALLOWED.lines()[0], interpreter="/nonexistent"
    )

    assert (finished.returncode, finished.stdout) == (0, "")


def test_the_hook_blocks_the_call_when_neither_guard_can_run(
    tmp_path: Path,
):
    """
    A plugin without its source stands in for an install that fails, so nothing is
    downloaded, and leaves the coarse guard nothing to run.
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


def test_the_hook_denies_a_command_naming_git_when_the_guard_fails():
    finished = run_hook("git log 'unbalanced")

    output = json.loads(finished.stdout)[HookKey.HOOK_SPECIFIC_OUTPUT]
    assert output[HookKey.PERMISSION_DECISION] == HookValue.DENY
