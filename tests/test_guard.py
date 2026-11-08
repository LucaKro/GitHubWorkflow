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

import domain_model
import pytest
from domain_model.claude_code.hooks import (
    FileWritingTool,
    HookInput,
    HookKey,
    HookValue,
)
from domain_model.locations import PathEnumeration
from domain_model.shell import CommandLine

import github_workflow
import github_workflow.guard as guard
from github_workflow.command_line import RefusalAdvice
from github_workflow.environment import WorkflowVariable
from github_workflow.guard import (
    CommandGuard,
    DescribeAlternative,
    DraftAlternative,
    GitHubCliWrite,
    GitHubToolWrite,
    GitWrite,
    ToolGuard,
    WorkflowAlternative,
)

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
def test_a_read_is_let_through(command: str) -> None:
    assert CommandGuard().denial(command) is None


@pytest.mark.parametrize("command", GuardDataset.DENIED.lines())
def test_a_write_is_denied(command: str) -> None:
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
def test_a_redirection_is_no_word_of_its_command(
    command: str, words: list[str]
) -> None:
    assert CommandLine(command).simple_commands() == [words]


def test_a_here_document_a_program_reads_is_data() -> None:
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
def test_a_write_around_a_here_document_is_denied(location: GuardDataset) -> None:
    assert CommandGuard().denial(location.value.read_text()) is not None


# %% what to do instead


@pytest.mark.parametrize("write", [*GitWrite, *GitHubCliWrite, *GitHubToolWrite])
def test_every_write_with_a_workflow_command_has_its_alternative(write: str) -> None:
    assert write in WorkflowAlternative.doing(write).writes


@pytest.mark.parametrize("write", list(GitWrite))
def test_a_git_write_names_the_workflow_command_doing_its_job(write: GitWrite) -> None:
    denial = CommandGuard().denial(f"git {write} feature")

    assert denial.instead == WorkflowAlternative.doing(write).command_line()


def test_opening_a_pull_request_names_the_workflow_s_draft() -> None:
    denial = CommandGuard().denial("gh pr create --title Change")

    assert denial.instead == DraftAlternative().command_line()


def test_editing_a_pull_request_names_the_workflow_s_describe() -> None:
    denial = CommandGuard().denial("gh pr edit 9 --body-file description.md")

    assert denial.instead == DescribeAlternative().command_line()


def test_a_write_no_workflow_command_does_names_none() -> None:
    denial = CommandGuard().denial("gh pr merge 9")

    assert denial.instead is None


# %% other tools


@pytest.mark.parametrize(
    "tool",
    [
        f"{HookValue.MCP_TOOL_PREFIX}github__get_file_contents",
        f"{HookValue.MCP_TOOL_PREFIX}github__list_pull_requests",
    ]
    + [
        f"{HookValue.MCP_TOOL_PREFIX}github__search_code",
        f"{HookValue.MCP_TOOL_PREFIX}github__pull_request_read",
        "Read",
    ]
    + [
        f"{HookValue.MCP_TOOL_PREFIX}github__actions_list",
        f"{HookValue.MCP_TOOL_PREFIX}github__actions_get",
    ],
)
def test_a_reading_tool_is_let_through(tool: str) -> None:
    assert ToolGuard(HookInput.from_json({HookKey.TOOL_NAME: tool})).denial() is None


@pytest.mark.parametrize(
    "tool",
    [
        f"{HookValue.MCP_TOOL_PREFIX}github__create_pull_request",
        f"{HookValue.MCP_TOOL_PREFIX}github__merge_pull_request",
    ]
    + [
        f"{HookValue.MCP_TOOL_PREFIX}github__issue_write",
        f"{HookValue.MCP_TOOL_PREFIX}github__actions_run_trigger",
    ],
)
def test_a_github_tool_that_writes_is_denied(tool: str) -> None:
    assert (
        ToolGuard(HookInput.from_json({HookKey.TOOL_NAME: tool})).denial() is not None
    )


@pytest.mark.parametrize("tool", list(GitHubToolWrite))
def test_a_github_tool_with_a_workflow_command_names_it(tool: GitHubToolWrite) -> None:
    denial = ToolGuard(
        HookInput.from_json(
            {HookKey.TOOL_NAME: f"{HookValue.MCP_TOOL_PREFIX}github__{tool}"}
        )
    ).denial()

    assert denial.instead == WorkflowAlternative.doing(tool).command_line()


def test_every_denial_says_how_to_report_an_unnecessary_one() -> None:
    """
    A session blocked by mistake learns where to say so, right where it is blocked.
    """
    command = GuardDataset.DENIED.lines()[0]

    assert RefusalAdvice.pointer() in CommandGuard().denial(command).message()


def test_a_refusal_leaves_the_filing_hint_to_the_notes() -> None:
    message = CommandGuard().denial("git push").message()

    assert RefusalAdvice.hint() not in message


def test_every_denial_says_never_to_get_around_it() -> None:
    command = GuardDataset.DENIED.lines()[0]

    assert RefusalAdvice.workaround_ban() in CommandGuard().denial(command).message()


# %% the person's commands, and the workflow's


@pytest.mark.parametrize("command", GuardDataset.PERSON_ONLY.lines())
def test_a_command_only_the_person_runs_is_denied_not_asked(command: str) -> None:
    """
    Not even the person's go-ahead lets a session run it.
    """
    output = ToolGuard(HookInput.from_json(hook_input(command))).output()[
        HookKey.HOOK_SPECIFIC_OUTPUT
    ]

    assert output[HookKey.PERMISSION_DECISION] == HookValue.DENY


@pytest.mark.parametrize("command", GuardDataset.WITHOUT_GO_AHEAD.lines())
def test_a_workflow_command_runs_without_the_person_being_asked(command: str) -> None:
    assert ToolGuard(HookInput.from_json(hook_input(command))).output() is None


def test_a_write_chained_to_a_workflow_command_is_still_denied() -> None:
    command = f"{GuardDataset.WITHOUT_GO_AHEAD.lines()[0]} && git push"

    output = ToolGuard(HookInput.from_json(hook_input(command))).output()[
        HookKey.HOOK_SPECIFIC_OUTPUT
    ]

    assert output[HookKey.PERMISSION_DECISION] == HookValue.DENY


# %% files git runs programs from


@pytest.mark.parametrize("tool", list(FileWritingTool))
@pytest.mark.parametrize(
    "path", ["/checkout/.git/config", ".git/hooks/pre-push", "/checkout/.gitconfig"]
)
def test_writing_a_file_git_runs_programs_from_is_denied(
    tool: FileWritingTool, path: str
) -> None:
    hook_input = {
        HookKey.TOOL_NAME: tool,
        HookKey.TOOL_INPUT: {HookKey.FILE_PATH: path},
    }

    assert ToolGuard(HookInput.from_json(hook_input)).denial() is not None


@pytest.mark.parametrize("path", ["/checkout/src/module.py", "/checkout/.gitignore"])
def test_writing_another_file_is_let_through(path: str) -> None:
    hook_input = {
        HookKey.TOOL_NAME: FileWritingTool.WRITE,
        HookKey.TOOL_INPUT: {HookKey.FILE_PATH: path},
    }

    assert ToolGuard(HookInput.from_json(hook_input)).denial() is None


@pytest.mark.parametrize("tool", list(FileWritingTool))
def test_the_hook_runs_for_the_tools_writing_files(tool: FileWritingTool) -> None:
    configuration = json.loads(GuardDataset.HOOK_CONFIGURATION.value.read_text())
    [guard] = configuration[HookKey.HOOKS][HookValue.PRE_TOOL_USE]

    assert re.fullmatch(guard[HookKey.MATCHER], tool)


# %% denials the person is shown


@pytest.mark.parametrize("command", GuardDataset.DENIED_UNSEEN.lines())
def test_a_command_denied_unseen_is_shown_to_the_person(command: str) -> None:
    """
    The person judges how often the guard denies what it cannot see into, and so whether
    that rule is worth its cost.
    """
    output = ToolGuard(HookInput.from_json(hook_input(command))).output()

    assert output[HookKey.HOOK_SPECIFIC_OUTPUT][HookKey.PERMISSION_DECISION] == (
        HookValue.DENY
    )
    assert command in output[HookKey.SYSTEM_MESSAGE]


@pytest.mark.parametrize("command", GuardDataset.DENIED.lines())
def test_a_write_the_guard_saw_is_not_shown_to_the_person(command: str) -> None:
    output = ToolGuard(HookInput.from_json(hook_input(command))).output()

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


def test_the_hook_denies_a_write_and_says_what_to_run_instead() -> None:
    command = GuardDataset.DENIED.lines()[0]

    finished = run_hook(command)

    output = json.loads(finished.stdout)[HookKey.HOOK_SPECIFIC_OUTPUT]
    assert output[HookKey.PERMISSION_DECISION] == HookValue.DENY
    assert (
        output[HookKey.PERMISSION_DECISION_REASON]
        == CommandGuard().denial(command).message()
    )


def test_the_hook_says_nothing_about_a_read() -> None:
    finished = run_hook(GuardDataset.ALLOWED.lines()[0])

    assert (finished.returncode, finished.stdout) == (0, "")


def test_the_hook_lets_a_read_through_when_the_runtime_cannot_run() -> None:
    """
    The guard runs from the plugin's source instead, judging the call as usual.
    """
    finished = run_hook(GuardDataset.ALLOWED.lines()[0], interpreter="/nonexistent")

    assert (finished.returncode, finished.stdout) == (0, "")


def test_the_hook_denies_a_write_when_the_runtime_cannot_run() -> None:
    finished = run_hook(GuardDataset.DENIED.lines()[0], interpreter="/nonexistent")

    output = json.loads(finished.stdout)[HookKey.HOOK_SPECIFIC_OUTPUT]
    assert output[HookKey.PERMISSION_DECISION] == HookValue.DENY


def test_the_guard_runs_on_the_standard_library_and_the_plugin_s_source_alone() -> None:
    """
    Without site-packages, only the standard library and the plugin's source, the domain
    model's included, can be imported.
    """
    sources = [
        str(Path(package.__file__).parents[1])
        for package in (github_workflow, domain_model)
    ]
    imported = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-c",
            f"import sys; sys.path[:0] = {sources!r}; import {guard.__name__}",
        ],
        capture_output=True,
        text=True,
    )

    assert (imported.returncode, imported.stderr) == (0, "")


def test_the_hook_lets_other_work_run_when_the_guard_cannot_run() -> None:
    """
    A broken runtime stops only what could reach git or GitHub, not every command.
    """
    finished = run_hook(
        CoarseGuardDataset.ALLOWED.lines()[0], interpreter="/nonexistent"
    )

    assert (finished.returncode, finished.stdout) == (0, "")


def test_the_hook_blocks_the_call_when_neither_guard_can_run(
    tmp_path: Path,
) -> None:
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


def test_the_hook_denies_a_command_naming_git_when_the_guard_fails() -> None:
    finished = run_hook("git log 'unbalanced")

    output = json.loads(finished.stdout)[HookKey.HOOK_SPECIFIC_OUTPUT]
    assert output[HookKey.PERMISSION_DECISION] == HookValue.DENY
