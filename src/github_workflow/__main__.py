"""
The workflow's commands, the only way its agent writes to git and GitHub; each checks
the owner's rules before it writes and prints one line saying what it did.

Usage: ``python -m github_workflow <command> ...``; ``--help`` lists the commands.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import TracebackType

from basstler_domain_model.exceptions import DataclassException

from github_workflow.command_line import RunnableCommand
from github_workflow.hooks import Speaker
from github_workflow.session import WorkflowSession
from github_workflow.settings import WorkflowSettings

# %% entry point


def report(
    kind: type[BaseException], raised: BaseException, traceback: TracebackType | None
) -> None:
    """
    Print a refusal of the workflow's as its reason and what to do instead, nothing
    more, and any other error as Python would.

    :param kind: The error's type.
    :param raised: The error.
    :param traceback: Where it was raised.
    """
    if not isinstance(raised, DataclassException):
        sys.__excepthook__(kind, raised, traceback)
        return
    print(Speaker.WORKFLOW.says(str(raised)), file=sys.stderr)


def main() -> None:
    """
    Run the command the command line names, and print what it did, or why it refused.
    """
    sys.excepthook = report
    arguments = RunnableCommand.parser().parse_args()
    session = WorkflowSession(Path.cwd(), WorkflowSettings())
    print(Speaker.WORKFLOW.says(session.command(arguments).run()))


if __name__ == "__main__":
    main()
