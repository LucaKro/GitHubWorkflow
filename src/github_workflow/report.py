"""
Compute one section of the session start, in a process of its own so a failure or a slow
answer costs only that section.

Usage: ``python -m github_workflow.report <section>``; prints one report line as JSON
per line, or nothing when there is nothing to say.
"""

from __future__ import annotations

import sys
from enum import StrEnum
from pathlib import Path

from basstler_domain_model.github.repository_client import GitHubRepository

from github_workflow.checkout import ProjectCheckout
from github_workflow.cleanup import CleanupReminder, KeptBranches
from github_workflow.findings import FindingsSummary
from github_workflow.notes.branch import NotesBranch
from github_workflow.pull_request_overview import (
    PullRequestOverview,
    PullRequestSignalReader,
)
from github_workflow.remotes import OwnedRemotes
from github_workflow.report_section import ReportSection, SectionContext
from github_workflow.repository_setup import RepositorySetup
from github_workflow.settings import WorkflowSettings

# %% the sections


class SectionName(StrEnum):
    """
    The sections of the session start that read the owner's repository on GitHub.
    """

    SETUP = "setup"
    """
    The repository features the workflow relies on.
    """

    PULL_REQUESTS = "pull-requests"
    """
    The open pull requests and their signals.
    """

    FINDINGS = "findings"
    """
    The findings waiting for the person.
    """

    CLEANUP = "cleanup"
    """
    The branches ready for deletion.
    """

    def section(self, context: SectionContext) -> ReportSection:
        """
        :param context: Where the section looks.
        :return: The section.
        """
        match self:
            case SectionName.SETUP:
                return RepositorySetup(context.remote.repository, context.github)
            case SectionName.PULL_REQUESTS:
                return PullRequestOverview(
                    PullRequestSignalReader.of(context.github),
                    context.github,
                    context.checkout.git.checked_out_branch(),
                )
            case SectionName.FINDINGS:
                return FindingsSummary(context.github)
            case SectionName.CLEANUP:
                return CleanupReminder(
                    KeptBranches.read(
                        context.checkout.git,
                        context.remote,
                        context.github,
                        NotesBranch.on(
                            context.checkout.git, context.remote, WorkflowSettings()
                        ),
                    )
                )


# %% entry point


def main() -> None:
    """
    Compute the section the command line names, and print its lines.
    """
    checkout = ProjectCheckout.containing(Path.cwd())
    remote = OwnedRemotes.read(checkout.git, WorkflowSettings()).chosen
    context = SectionContext(
        checkout, remote, GitHubRepository.from_environment(remote.repository)
    )
    for line in SectionName(sys.argv[1]).section(context).lines():
        print(line.json())


if __name__ == "__main__":
    main()
