"""
Which Bash command lines are a workflow command a Claude Code session runs on its own,
which the plugin's mod approves so auto mode's classifier does not judge them: the
launcher running one such command, with nothing around it but changing directory and
printing part of its output.

Runs on the standard library alone, like :mod:`github_workflow.guard`, so the mod can run
it from the plugin's source.

Usage: ``python -m github_workflow.approval < command-line``; exits with
:attr:`ApprovalStatus.APPROVED` when a session may run the line on its own, and with
another status otherwise, a line it cannot read included.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from enum import IntEnum, StrEnum

from github_workflow.command_line import (
    BranchSubcommand,
    FindingSubcommand,
    IdeaSubcommand,
    NotesSubcommand,
    ReviewSubcommand,
    WorkflowCommand,
)
from github_workflow.guard import CommandGuard, CommandLine, SimpleCommand
from github_workflow.install import Launcher

# %% the commands


class SessionCommand(StrEnum):
    """
    The workflow commands a session runs on its own, never on the person's word, by
    their leading words.
    """

    BRANCH_START = f"{WorkflowCommand.BRANCH} {BranchSubcommand.START}"
    BRANCH_SWITCH = f"{WorkflowCommand.BRANCH} {BranchSubcommand.SWITCH}"
    BRANCH_DISCARD = f"{WorkflowCommand.BRANCH} {BranchSubcommand.DISCARD}"
    COMMIT = WorkflowCommand.COMMIT.value
    PUSH = WorkflowCommand.PUSH.value
    DRAFT = WorkflowCommand.DRAFT.value
    SYNC = WorkflowCommand.SYNC.value
    NOTES_SAVE = f"{WorkflowCommand.NOTES} {NotesSubcommand.SAVE}"
    FINDING_FILE = f"{WorkflowCommand.FINDING} {FindingSubcommand.FILE}"
    FINDING_LIST = f"{WorkflowCommand.FINDING} {FindingSubcommand.LIST}"
    FINDING_CLOSE = f"{WorkflowCommand.FINDING} {FindingSubcommand.CLOSE}"
    FINDING_COMMENT = f"{WorkflowCommand.FINDING} {FindingSubcommand.COMMENT}"
    FINDING_PROVE = f"{WorkflowCommand.FINDING} {FindingSubcommand.PROVE}"
    FINDING_MARK_UNPROVEN = (
        f"{WorkflowCommand.FINDING} {FindingSubcommand.MARK_UNPROVEN}"
    )
    FINDING_RECHECK = f"{WorkflowCommand.FINDING} {FindingSubcommand.RECHECK}"
    IDEA_FILE = f"{WorkflowCommand.IDEA} {IdeaSubcommand.FILE}"
    CLEANUP = WorkflowCommand.CLEANUP.value
    DETAILS = WorkflowCommand.DETAILS.value
    CLONE = WorkflowCommand.CLONE.value
    LABEL = WorkflowCommand.LABEL.value
    REVIEW_LIST = f"{WorkflowCommand.REVIEW} {ReviewSubcommand.LIST}"
    REVIEW_REPLY = f"{WorkflowCommand.REVIEW} {ReviewSubcommand.REPLY}"
    REVIEW_RESOLVE = f"{WorkflowCommand.REVIEW} {ReviewSubcommand.RESOLVE}"
    REVIEW_ADDRESSED = f"{WorkflowCommand.REVIEW} {ReviewSubcommand.ADDRESSED}"
    DESCRIBE = WorkflowCommand.DESCRIBE.value
    """
    Only of the work branch's own pull request: ``describe`` naming another's number is
    the person's word.
    """

    @classmethod
    def run_by(cls, words: list[str]) -> SessionCommand | None:
        """
        :param words: A workflow command's words, options left out.
        :return: The command a session runs on its own that they run, ``None`` when
            they run another.
        """
        command = next(
            (
                member
                for member in cls
                if words[: len(member.split())] == member.split()
            ),
            None,
        )
        names_a_number = any(word.isdigit() for word in words[1:])
        if command is cls.DESCRIBE and names_a_number:
            return None
        return command


class HarmlessProgram(StrEnum):
    """
    The programs a line running a workflow command may also run: each only changes
    directory or prints part of what it reads.
    """

    CD = "cd"
    HEAD = "head"
    TAIL = "tail"


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
        return SessionCommand.run_by(workflow[0].workflow_words() or []) is not None

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
        harmless = command.program in HarmlessProgram._value2member_map_
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
