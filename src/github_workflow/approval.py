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
import tempfile
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from pathlib import Path

from domain_model.class_property import classproperty
from domain_model.shell import CommandLine, SimpleCommand

from github_workflow.command_line import CommandOption, RunnableCommand
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


class OutputFilterOption(StrEnum):
    """
    The options of :attr:`HarmlessProgram.HEAD` and :attr:`HarmlessProgram.TAIL`
    followed by a count of their own, which is no file.
    """

    LINES = "--lines"
    """
    How many lines to print.
    """

    LINES_SHORT = "-n"
    """
    How many lines to print, short form.
    """

    BYTES = "--bytes"
    """
    How many bytes to print.
    """

    BYTES_SHORT = "-c"
    """
    How many bytes to print, short form.
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
        commands = CommandLine(self.command_line).simple_commands()
        workflow = [command for command in commands if self.is_workflow(command)]
        if len(workflow) != 1:
            return False
        others = [command for command in commands if command not in workflow]
        if not all(self.is_harmless(command) for command in others):
            return False
        directory = self.directory_reached(commands[: commands.index(workflow[0])])
        if directory is None or self.reaches_outside(workflow[0], directory):
            return False
        words = WorkflowInvocation(workflow[0]).words() or []
        command = RunnableCommand.from_words(words)
        return command is not None and command.runs_unasked(words)

    @classproperty
    def path_options(cls) -> tuple[CommandOption, ...]:
        """
        The options of workflow commands naming a file the command reads or runs.
        """
        return (CommandOption.BODY_FILE, CommandOption.TEST, CommandOption.PYTHON)

    @classproperty
    def interpreter_prefix(cls) -> str:
        """
        How the name of an interpreter on the path, given to
        :attr:`CommandOption.PYTHON` without a directory, starts.
        """
        return "python"

    @staticmethod
    def directory_reached(changes: list[SimpleCommand]) -> Path | None:
        """
        :param changes: The commands run before the workflow's, ``cd`` among them.
        :return: The directory the workflow command runs in, ``None`` when a ``cd``
            names no directory.
        """
        directory = Path.cwd()
        for change in changes:
            if change.program != HarmlessProgram.CD:
                continue
            target = (change.arguments or ["~"])[0]
            if target.startswith("-"):
                return None
            directory = (directory / Path(target).expanduser()).resolve()
        return directory

    def reaches_outside(self, command: SimpleCommand, directory: Path) -> bool:
        """
        :param command: The workflow command.
        :param directory: Where it runs.
        :return: Whether a file one of its :attr:`path_options` names lies outside the
            working directory and the temporary directory, links followed.
        """
        places = [Path.cwd().resolve(), Path(tempfile.gettempdir()).resolve()]
        arguments = command.arguments
        given: list[tuple[CommandOption, str]] = []
        for index, argument in enumerate(arguments):
            option, joined, value = argument.partition("=")
            if option not in self.path_options:
                continue
            following = arguments[index + 1 : index + 2]
            given.extend((CommandOption(option), file) for file in [value] if joined)
            given.extend(
                (CommandOption(option), file) for file in following if not joined
            )
        for option, value in given:
            on_path = "/" not in value and value.startswith(self.interpreter_prefix)
            if option is CommandOption.PYTHON and on_path:
                continue
            located = (directory / Path(value).expanduser()).resolve()
            if not any(located.is_relative_to(place) for place in places):
                return True
        return False

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
            nothing assigned and no file named for it to print.
        """
        if command.program not in HarmlessProgram or command.assignments:
            return False
        if command.program == HarmlessProgram.CD:
            return True
        arguments = command.arguments
        counts = {
            index + 1
            for index, argument in enumerate(arguments)
            if argument in OutputFilterOption
        }
        return all(
            argument.startswith("-") or index in counts
            for index, argument in enumerate(arguments)
        )


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
