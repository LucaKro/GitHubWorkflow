"""
Which Bash command lines the plugin's mod approves, so auto mode's classifier does not
judge them: the launcher running one workflow command a session runs on its own, with
nothing around it but changing directory and printing part of its output.

Runs on the standard library and the plugin's own source alone, like
:mod:`github_workflow.guard`.

Usage: ``python -m github_workflow.approval < command-line``; exits with
:attr:`ApprovalStatus.APPROVED` when a session may run the line on its own, and with
another status otherwise, a line it cannot read included.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from enum import IntEnum, StrEnum

from basstler_domain_model.shell import CommandLine, SimpleCommand

from github_workflow.command_line import RunnableCommand
from github_workflow.guard import CommandGuard, WorkflowInvocation
from github_workflow.plugin import Launcher

# %% what a line may run besides


class HarmlessProgram(StrEnum):
    """
    The programs a line running a workflow command may also run: each only changes
    directory or prints part of what it reads.
    """

    CD = "cd"
    """
    Changes directory.
    """

    HEAD = "head"
    """
    Prints the start of what it reads.
    """

    TAIL = "tail"
    """
    Prints the end of what it reads.
    """


class ApprovalStatus(IntEnum):
    """
    How :func:`main` exits.
    """

    APPROVED = 0
    """
    A session may run the line on its own.
    """

    LEFT = 1
    """
    The line is left to the session's permissions.
    """


# %% judging a line


@dataclass(frozen=True)
class SessionCommandApproval:
    """
    Whether one Bash command line runs exactly one workflow command a session runs on
    its own, through the launcher, with nothing else but ``cd`` and output filters.
    """

    command_line: str
    """
    The command line.
    """

    def approves(self) -> bool:
        """
        :return: Whether a session may run the line without anyone judging it.
        :raises ValueError: If its quotes do not balance.
        """
        unredirected = self.command_line.replace("2>&1", "")
        if re.search(r"[$`()<>]", unredirected):
            return False
        if CommandGuard().denial(self.command_line) is not None:
            return False
        commands = [
            SimpleCommand(words)
            for words in CommandLine(self.command_line).simple_commands()
        ]
        workflow = [command for command in commands if self.is_workflow(command)]
        if len(workflow) != 1:
            return False
        others = [command for command in commands if command not in workflow]
        if not all(self.is_harmless(command) for command in others):
            return False
        words = WorkflowInvocation(workflow[0]).words() or []
        command = RunnableCommand.run_by(words)
        return command is not None and command.runs_unasked(words)

    @staticmethod
    def is_workflow(command: SimpleCommand) -> bool:
        """
        :param command: One simple command.
        :return: Whether it runs the launcher, by its bare name, with nothing assigned.
        """
        runs_launcher = command.words[command.program_start :][:1] == [Launcher.COMMAND]
        return runs_launcher and not command.assignments

    @staticmethod
    def is_harmless(command: SimpleCommand) -> bool:
        """
        :param command: One simple command beside the workflow's.
        :return: Whether it only changes directory or prints part of its input, with
            nothing assigned.
        """
        harmless = command.program in HarmlessProgram
        return harmless and not command.assignments


# %% entry point


def main() -> None:
    """
    Read a command line on standard input, and exit with whether a session may run it on
    its own.
    """
    approval = SessionCommandApproval(sys.stdin.read())
    status = ApprovalStatus.APPROVED if approval.approves() else ApprovalStatus.LEFT
    sys.exit(status)


if __name__ == "__main__":
    main()
