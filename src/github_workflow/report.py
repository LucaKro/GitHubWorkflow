"""
Compute one section of the session start, run in a process of its own.

Usage: ``python -m github_workflow.report <section>``; prints one report line as JSON
per line, or nothing when there is nothing to say.
"""

from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from domain_model.class_property import classproperty
from domain_model.github.repository_client import GitHubRepository

from github_workflow.cleanup import CleanupReminder
from github_workflow.findings import FindingsSummary
from github_workflow.freshness import FreshnessReport
from github_workflow.label_events import LabelsCompletedReport
from github_workflow.pull_request_overview import PullRequestOverview
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


# %% building a section


@dataclass(frozen=True)
class SectionBuilder(ABC):
    """
    Builds one section from the checkout the session starts in.
    """

    session: WorkflowSession
    """
    The checkout the session starts in.
    """

    @classproperty
    @abstractmethod
    def section_name(cls) -> SectionName:
        """
        The section this builds.
        """

    @abstractmethod
    def section(self) -> ReportSection:
        """
        :return: The section.
        """

    @classmethod
    def building(cls, name: SectionName) -> type[SectionBuilder]:
        """
        :param name: A section.
        :return: The class building it.
        """
        return next(
            builder for builder in cls.__subclasses__() if builder.section_name is name
        )


@dataclass(frozen=True)
class SetupBuilder(SectionBuilder):
    """
    Builds the section turning on the repository features the workflow relies on.
    """

    @classproperty
    def section_name(cls) -> SectionName:
        return SectionName.SETUP

    def section(self) -> ReportSection:
        return RepositorySetup(self.session.remote.repository, self.session.github)


@dataclass(frozen=True)
class PullRequestsBuilder(SectionBuilder):
    """
    Builds the section over the open pull requests.
    """

    @classproperty
    def section_name(cls) -> SectionName:
        return SectionName.PULL_REQUESTS

    def section(self) -> ReportSection:
        github = self.session.github
        return PullRequestOverview(
            github,
            self.session.thread_source,
            self.session.checkout.checked_out_branch_name,
        )


@dataclass(frozen=True)
class FindingsBuilder(SectionBuilder):
    """
    Builds the section over the findings waiting for the person.
    """

    @classproperty
    def section_name(cls) -> SectionName:
        return SectionName.FINDINGS

    def section(self) -> ReportSection:
        return LabelsCompletedReport(
            self.session.label_completion,
            FindingsSummary(self.session.github, self.session.remote.repository),
        )


@dataclass(frozen=True)
class CleanupBuilder(SectionBuilder):
    """
    Builds the section over the branches ready for deletion.
    """

    @classproperty
    def section_name(cls) -> SectionName:
        return SectionName.CLEANUP

    def section(self) -> ReportSection:
        return CleanupReminder(self.session.kept_branches)


@dataclass(frozen=True)
class FreshnessBuilder(SectionBuilder):
    """
    Builds the section bringing the fork's default branch and the work branch up to
    date.
    """

    @classproperty
    def section_name(cls) -> SectionName:
        return SectionName.FRESHNESS

    def section(self) -> ReportSection:
        return FreshnessReport(self.session.freshening)


@dataclass(frozen=True)
class UpstreamMergesBuilder(SectionBuilder):
    """
    Builds the section following the fork's pull requests merged upstream.
    """

    @classproperty
    def section_name(cls) -> SectionName:
        return SectionName.UPSTREAM_MERGES

    def section(self) -> ReportSection:
        return UpstreamMergeFollowing(
            self.session.remote.repository.owner,
            self.session.github,
            GitHubRepository.from_environment,
            self.session.session_closing,
            self.session.placement,
        )


# %% entry point


def main() -> None:
    """
    Compute the section the command line names, and print its lines.
    """
    session = WorkflowSession(Path.cwd(), WorkflowSettings())
    builder = SectionBuilder.building(SectionName(sys.argv[1]))
    for line in builder(session).section().lines():
        print(line.to_json())


if __name__ == "__main__":
    main()
