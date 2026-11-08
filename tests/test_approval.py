"""
Tests for :mod:`github_workflow.approval`: a command line running exactly one workflow
command a session runs on its own, through the launcher, is approved; every other line
is left to the session's permissions.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from basstler_domain_model.locations import PathEnumeration

from github_workflow import approval
from github_workflow.approval import ApprovalStatus, SessionCommandApproval
from github_workflow.plugin import Launcher

# %% the command lines


class ApprovalDataset(PathEnumeration):
    """
    Command lines the mod approves, and those it leaves.
    """

    APPROVED = Path(__file__).parent / "dataset" / "approval" / "approved.sh"
    """
    One command line per line, each a session's own workflow command.
    """

    LEFT = Path(__file__).parent / "dataset" / "approval" / "left.sh"
    """
    One command line per line, each needing the person's word or running more.
    """

    def lines(self) -> list[str]:
        """:return: Every command line in the file, comments left out."""
        return [
            line
            for line in self.value.read_text().splitlines()
            if line and not line.startswith("#")
        ]


@pytest.mark.parametrize("command_line", ApprovalDataset.APPROVED.lines())
def test_a_session_s_own_workflow_command_is_approved(command_line: str) -> None:
    assert SessionCommandApproval(command_line).approves() is True


@pytest.mark.parametrize("command_line", ApprovalDataset.LEFT.lines())
def test_any_other_line_is_left(command_line: str) -> None:
    assert SessionCommandApproval(command_line).approves() is False


# %% entry point


@pytest.mark.parametrize(
    "command_line, status",
    [
        (ApprovalDataset.APPROVED.lines()[0], ApprovalStatus.APPROVED),
        (ApprovalDataset.LEFT.lines()[0], ApprovalStatus.LEFT),
    ],
    ids=["approved", "left"],
)
def test_the_check_exits_with_its_verdict(
    command_line: str, status: ApprovalStatus
) -> None:
    finished = subprocess.run(
        [sys.executable, "-m", approval.__name__],
        input=command_line,
        capture_output=True,
        text=True,
    )

    assert finished.returncode == status


def test_a_line_whose_quotes_do_not_balance_is_not_approved() -> None:
    finished = subprocess.run(
        [sys.executable, "-m", approval.__name__],
        input=f"{Launcher.COMMAND} push 'unbalanced",
        capture_output=True,
        text=True,
    )

    assert finished.returncode != ApprovalStatus.APPROVED
