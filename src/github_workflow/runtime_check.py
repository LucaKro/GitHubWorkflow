"""
Whether a runtime runs the workflow: its guard denies a push, and its commands load.

Usage: ``python -m github_workflow.runtime_check``; exits with
:attr:`RuntimeCheckStatus.WORKS` when the runtime works, and otherwise prints what failed.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from enum import IntEnum

from basstler_domain_model.claude_code.hooks import HookInput, HookValue

import github_workflow.session  # noqa: F401 - checks that the commands load
from github_workflow.command_line import RunnableCommand
from github_workflow.guard import ToolGuard

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

    def failure(self) -> str | None:
        """
        :return: What failed, ``None`` when the runtime works.
        """
        call = HookInput(HookValue.BASH_TOOL, self.probed_command)
        if ToolGuard(call).denial() is None:
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
