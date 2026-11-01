"""
Running a command and keeping what it said, whether or not it succeeded.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

# %% a finished command


@dataclass(frozen=True)
class CommandResult:
    """
    One finished command, or one that could not start.
    """

    arguments: tuple[str, ...]
    """
    The command and its arguments, as invoked.
    """

    exit_status: int | None
    """
    The status it exited with, ``None`` when the command is not installed.
    """

    output: str
    """
    Its stripped standard output.
    """

    error_output: str
    """
    Its stripped standard error, or why it could not start.
    """

    seconds: float
    """
    How long it ran.
    """

    @property
    def succeeded(self) -> bool:
        """:return: Whether it exited zero."""
        return self.exit_status == 0

    @property
    def first_line(self) -> str:
        """:return: Its first line of output on success, of error output otherwise."""
        return (self.output if self.succeeded else self.error_output).partition("\n")[0]

    @property
    def summary(self) -> str:
        """:return: Its last line of output on success, of error output otherwise."""
        text = self.output if self.succeeded else self.error_output
        lines = text.splitlines()
        return lines[-1] if lines else ""


# %% running one


@dataclass(frozen=True)
class CommandRunner:
    """
    Runs commands in one directory, reporting a failure as a result rather than raising.
    """

    working_directory: Path
    """
    The directory every command runs in.
    """

    def run(self, *arguments: str, standard_input: str | None = None) -> CommandResult:
        """
        :param arguments: The command and its arguments.
        :param standard_input: What to write to its standard input, if anything.
        :return: The finished command.
        """
        if shutil.which(arguments[0]) is None:
            return CommandResult(
                arguments, None, "", f"{arguments[0]} is not installed", 0.0
            )
        started = time.monotonic()
        completed = subprocess.run(
            arguments,
            cwd=self.working_directory,
            input=standard_input,
            capture_output=True,
            text=True,
        )
        return CommandResult(
            arguments,
            completed.returncode,
            completed.stdout.strip(),
            completed.stderr.strip(),
            round(time.monotonic() - started, 2),
        )
