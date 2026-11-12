"""
The workflow's commands, the only way its agent writes to git and GitHub; each checks
the owner's rules before it writes and prints one line saying what it did.

Usage: ``python -m github_workflow <command> ...``; ``--help`` lists the commands.
"""

from __future__ import annotations

import sys
from pathlib import Path

from github_workflow.command_line import RunnableCommand
from github_workflow.report_lines import FailureReport, Speaker
from github_workflow.session import WorkflowSession
from github_workflow.settings import WorkflowSettings

# %% entry point


def main() -> None:
    """
    Run the command the command line names, and print what it did, or why it refused.
    """
    sys.excepthook = FailureReport().report
    arguments = RunnableCommand.parser().parse_args()
    session = WorkflowSession(Path.cwd(), WorkflowSettings())
    print(Speaker.WORKFLOW.says(session.command(arguments).run()))


if __name__ == "__main__":
    main()
