"""
Compute one section of the session start, run in a process of its own.

Usage: ``python -m github_workflow.report <section>``; prints one report line as JSON
per line, or nothing when there is nothing to say.
"""

from __future__ import annotations

import sys
from enum import StrEnum
from pathlib import Path

from basstler_domain_model.github.repository_client import GitHubRepository

from github_workflow.cleanup import CleanupReminder
from github_workflow.findings import FindingsSummary
from github_workflow.freshness import FreshnessReport
from github_workflow.label_events import LabelsCompletedReport
from github_workflow.pull_request_overview import (
    PullRequestOverview,
    PullRequestSignalReader,
)
from github_workflow.report_section import ReportSection
from github_workflow.repository_setup import RepositorySetup
from github_workflow.session import WorkflowSession
from github_workflow.settings import WorkflowSettings
from github_workflow.upstream import UpstreamMergeFollowing

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
    The findings waiting for the person, once the labels picked on GitHub are completed.
    """

    CLEANUP = "cleanup"
    """
    The branches ready for deletion.
    """

    FRESHNESS = "freshness"
    """
    The fork's default branch and the work branch brought up to date.
    """

    UPSTREAM_MERGES = "upstream-merges"
    """
    The fork's pull requests merged upstream, closed, and their stacks moved on.
    """

    def section(self, session: WorkflowSession) -> ReportSection:
        """
        :param session: The checkout the session starts in.
        :return: The section.
        """
        github = session.github
        match self:
            case SectionName.SETUP:
                return RepositorySetup(session.remote.repository, github)
            case SectionName.PULL_REQUESTS:
                return PullRequestOverview(
                    PullRequestSignalReader.from_repository(github),
                    github,
                    github,
                    session.checkout.git.checked_out_branch(),
                )
            case SectionName.FINDINGS:
                return LabelsCompletedReport(
                    session.label_completion,
                    FindingsSummary(github, session.remote.repository),
                )
            case SectionName.CLEANUP:
                return CleanupReminder(session.kept_branches)
            case SectionName.UPSTREAM_MERGES:
                return UpstreamMergeFollowing(
                    session.remote.repository,
                    github,
                    github,
                    github,
                    GitHubRepository.from_environment,
                    session.session_closing,
                    session.placement,
                )
            case SectionName.FRESHNESS:
                return FreshnessReport(session.freshening)


# %% entry point


def main() -> None:
    """
    Compute the section the command line names, and print its lines.
    """
    session = WorkflowSession(Path.cwd(), WorkflowSettings())
    for line in SectionName(sys.argv[1]).section(session).lines():
        print(line.to_json())


if __name__ == "__main__":
    main()
