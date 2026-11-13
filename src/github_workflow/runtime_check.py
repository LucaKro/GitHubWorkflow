"""
Whether a runtime runs the workflow: every file the packages ship is there, its guard
denies a push, and its commands load.

Usage: ``python -m github_workflow.runtime_check``; exits with
:attr:`RuntimeCheckStatus.WORKS` when the runtime works, and otherwise prints what failed.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path

from domain_model.claude_code.hooks import HookValue, ShellCommandCall
from domain_model.class_property import classproperty
from domain_model.github.vocabulary import GraphQLDocument

import github_workflow.session  # noqa: F401 - checks that the commands load
from github_workflow.command_line import RunnableCommand
from github_workflow.guard import ToolGuard
from github_workflow.locations import ProbeTemplate, WorkflowTemplate

# %% the check


class RuntimeCheckStatus(IntEnum):
    """
    How :func:`main` exits.
    """

    WORKS = 0
    """
    The runtime runs the workflow.
    """

    BROKEN = 1
    """
    It does not.
    """


@dataclass(frozen=True)
class RuntimeCheck:
    """
    The checks a new runtime passes before it is switched over to.
    """

    probed_command: str = "git push"
    """
    A command line the guard denies.
    """

    @classproperty
    def shipped_files(cls) -> list[Path]:
        """
        The files the workflow and the domain model ship beside their modules.
        """
        return [
            *WorkflowTemplate,
            *ProbeTemplate,
            *(document.path for document in GraphQLDocument),
        ]

    def failure(self) -> str | None:
        """
        :return: What failed, ``None`` when the runtime works.
        """
        missing = [str(path) for path in self.shipped_files if not path.exists()]
        if missing:
            return f"the runtime lacks the shipped files {', '.join(missing)}"
        call = ShellCommandCall(HookValue.BASH_TOOL, self.probed_command)
        if call.request_decision(ToolGuard()) is None:
            return f"the guard let `{self.probed_command}` run"
        RunnableCommand.parser()
        return None


# %% entry point


def main() -> None:
    """
    Check the runtime this runs in, and exit with whether it works.
    """
    failure = RuntimeCheck().failure()
    if failure is not None:
        print(failure, file=sys.stderr)
        sys.exit(RuntimeCheckStatus.BROKEN)
    sys.exit(RuntimeCheckStatus.WORKS)


if __name__ == "__main__":
    main()
