"""
The owner's open pull requests, one line each with the signals that ask for attention:

failing checks, a conflict or a base moved on, and unresolved review threads - that they
are there, never what they say. The details come only when asked for.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from basstler_domain_model.github.pull_request_fields import (
    PullRequestField,
    PullRequestHead,
    PullRequestPayload,
)
from basstler_domain_model.github.pull_request_models import (
    UpstreamPullRequestSnapshot,
)
from basstler_domain_model.github.readers import PullRequestSource, ReadSource
from basstler_domain_model.github.repository_client import (
    GitHubRepository,
    PullRequestReader,
    ReviewRequests,
)
from basstler_domain_model.github.vocabulary import MergeableState

from github_workflow.hooks import ReportLine, Tone
from github_workflow.report_section import ReportSection
from github_workflow.work import WorkflowStep

# %% one pull request


@dataclass(frozen=True)
class PullRequestSignals:
    """
    What one open pull request is, and what in it asks for attention.
    """

    number: int
    """
    The pull request's number.
    """

    title: str
    """
    Its title.
    """

    branch: str
    """
    The branch it merges.
    """

    draft: bool
    """
    Whether it is a draft.
    """

    mergeable: str | None
    """
    GitHub's word on merging it, ``None`` while GitHub has not worked it out.
    """

    snapshot: UpstreamPullRequestSnapshot
    """
    Its checks and review threads.
    """

    @property
    def problems(self) -> list[str]:
        """:return: Each signal asking for attention, in a few words."""
        problems = []
        if self.snapshot.checks is not None and self.snapshot.checks.state.failed:
            problems.append("CI failing")
        if self.mergeable == MergeableState.DIRTY:
            problems.append("conflict")
        if self.mergeable == MergeableState.BEHIND:
            problems.append("behind its base")
        unresolved = len(self.snapshot.unresolved_threads)
        if unresolved:
            problems.append(
                f"{unresolved} unresolved thread{'s' if unresolved > 1 else ''}"
            )
        return problems

    def line(self, checked_out: str) -> ReportLine:
        """
        :param checked_out: The branch the session works on.
        :return: The pull request in one line, yellow when something asks for
            attention.
        """
        marks = ["this branch"] if self.branch == checked_out else []
        marks += ["draft"] if self.draft else []
        marks += self.problems or ["ok"]
        return ReportLine(
            f"github-workflow: #{self.number} {self.title} - {' · '.join(marks)}",
            Tone.ACTION if self.problems else Tone.NEWS,
        )


# %% reading them


@dataclass(frozen=True)
class PullRequestSignalReader:
    """
    Reads the signals of the owner's pull requests.
    """

    pull_requests: PullRequestReader
    """
    Lists and reads the pull requests.
    """

    reviews: PullRequestSource
    """
    Reads their checks and review threads.
    """

    @classmethod
    def of(cls, github: GitHubRepository) -> PullRequestSignalReader:
        """
        :param github: The owner's repository on GitHub.
        :return: A reader of its pull requests, reading review threads through the API
            the place this runs in can reach.
        """
        repository = github.repository
        threads = ReadSource.detect().reader(github.api, repository, repository.owner)
        return cls(github, threads)

    def signals(self, number: int) -> PullRequestSignals:
        """
        :param number: An open pull request.
        :return: What in it asks for attention.
        """
        with ThreadPoolExecutor() as pool:
            record = pool.submit(self.pull_requests.pull_request, number)
            snapshot = pool.submit(self.reviews.read_current_state, number)
        return self.signals_of(record.result(), snapshot.result())

    @staticmethod
    def signals_of(
        record: PullRequestPayload, snapshot: UpstreamPullRequestSnapshot
    ) -> PullRequestSignals:
        """
        :param record: The pull request, as read on its own.
        :param snapshot: Its checks and review threads.
        :return: What in it asks for attention.
        """
        number = PullRequestField.NUMBER.read(record)
        return PullRequestSignals(
            number,
            PullRequestField.TITLE.read(record, number),
            PullRequestHead.from_record(record, number).branch,
            bool(PullRequestField.DRAFT.read(record, number)),
            PullRequestField.MERGEABLE_STATE.read(record, number),
            snapshot,
        )


# %% the section


@dataclass(frozen=True)
class PullRequestOverview(ReportSection):
    """
    One line per open pull request, and how many wait on the person's review.
    """

    reader: PullRequestSignalReader
    """
    Reads the pull requests' signals.
    """

    requests: ReviewRequests
    """
    Counts the pull requests waiting on the person's review.
    """

    checked_out: str
    """
    The branch the session works on.
    """

    def lines(self) -> list[ReportLine]:
        with ThreadPoolExecutor() as pool:
            counted = pool.submit(self.requests.awaiting_my_review)
            numbers = [
                PullRequestField.NUMBER.read(record)
                for record in self.reader.pull_requests.open_pull_requests()
            ]
            read = list(pool.map(self.reader.signals, numbers))
        waiting = counted.result()
        lines = [signals.line(self.checked_out) for signals in read]
        if waiting:
            plural = "s wait" if waiting > 1 else " waits"
            lines.append(
                ReportLine(
                    f"github-workflow: {waiting} pull request{plural} on your review",
                    Tone.ACTION,
                )
            )
        return lines


# %% the details, when asked for


@dataclass(frozen=True)
class PullRequestDetails(WorkflowStep):
    """
    What the signals of one pull request are about: the failing checks with their links,
    the merge state, and where the unresolved threads are.
    """

    reader: PullRequestSignalReader
    """
    Reads the pull request's signals.
    """

    number: int
    """
    The pull request.
    """

    def run(self) -> str:
        """
        :return: The details, one per line; overrides :meth:`WorkflowStep.run`, which
            reports in one line.
        """
        signals = self.reader.signals(self.number)
        snapshot = signals.snapshot
        lines = [f"#{signals.number} {signals.title} - {snapshot.url}"]
        checks = snapshot.checks.unsuccessful if snapshot.checks else []
        lines += [
            f"check {check.outcome}: {check.name} {check.url}" for check in checks
        ]
        lines.append(f"merge state: {signals.mergeable or 'not worked out yet'}")
        for thread in snapshot.unresolved_threads:
            first = (
                thread.comments[0].body.strip().splitlines() if thread.comments else []
            )
            place = f"{thread.path}:{thread.line}" if thread.line else thread.path
            lines.append(f"unresolved thread at {place}: {''.join(first[:1])}")
        return "\n".join(lines)
