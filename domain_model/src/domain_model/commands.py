"""
Running a command and keeping what it said, whether or not it succeeded.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from collections.abc import Mapping
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
    The status it exited with, ``None`` when it did not finish: the command is not
    installed, or ran out of time.
    """

    standard_output: str
    """
    Its standard output, exactly as written.
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
    def output(self) -> str:
        """:return: Its standard output, stripped."""
        return self.standard_output.strip()

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

    def run(
        self,
        program: str,
        *arguments: str,
        standard_input: str | None = None,
        environment: Mapping[str, str] | None = None,
        timeout_seconds: float = 600.0,
    ) -> CommandResult:
        """
        :param program: The program to run.
        :param arguments: Its arguments.
        :param standard_input: What to write to its standard input, if anything.
        :param environment: Variables to set for this command on top of the process's
            own.
        :param timeout_seconds: How long the command may run before it is stopped.
        :return: The finished command.
        """
        command = (program, *arguments)
        if shutil.which(program) is None:
            return CommandResult(command, None, "", f"{program} is not installed", 0.0)
        started = time.monotonic()
        try:
            completed = subprocess.run(
                command,
                cwd=self.working_directory,
                input=standard_input,
                env={**os.environ, **(environment or {})},
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return CommandResult(
                command,
                None,
                "",
                f"{program} did not finish within {timeout_seconds} seconds",
                round(time.monotonic() - started, 2),
            )
        return CommandResult(
            command,
            completed.returncode,
            completed.stdout,
            completed.stderr.strip(),
            round(time.monotonic() - started, 2),
        )
