"""
The owner's open pull requests, one line each with the signals that ask for attention:

failing checks, a conflict or a base moved on, and unresolved review threads - that they
are there, never what they say, grouped by where each stands. The details come only
when asked for. The pull requests the person shelved are left out.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import StrEnum

from domain_model.github.number_links import NumberLink
from domain_model.github.pull_request_models import (
    UpstreamPullRequestSnapshot,
)
from domain_model.github.readers import PullRequestSource
from domain_model.github.repository_client import (
    PullRequestReader,
    PullRequestTracker,
)
from domain_model.github.rest_models import RestPullRequest
from domain_model.github.vocabulary import MergeableState

from github_workflow.labels import PullRequestLabel, UpstreamLabel
from github_workflow.report_lines import (
    CountedThing,
    Emphasis,
    Highlight,
    ReportLine,
    Speaker,
    Tone,
)
from github_workflow.report_section import ReportGroup, ReportSection
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

    url: str
    """
    Its page on GitHub.
    """

    draft: bool
    """
    Whether it is a draft.
    """

    opened_upstream: bool
    """
    Whether it is labelled as opened on the upstream repository.
    """

    mergeable: MergeableState | None
    """
    GitHub's word on merging it, ``None`` while GitHub has not worked it out.
    """

    snapshot: UpstreamPullRequestSnapshot
    """
    Its checks and review threads.
    """

    @classmethod
    def from_reads(
        cls, pull_request: RestPullRequest, snapshot: UpstreamPullRequestSnapshot
    ) -> PullRequestSignals:
        """
        :param pull_request: The pull request, as read on its own.
        :param snapshot: Its checks and review threads.
        :return: What in it asks for attention.
        """
        return cls(
            pull_request.number,
            pull_request.title,
            pull_request.head.branch,
            pull_request.url,
            pull_request.draft,
            UpstreamLabel.OPENED_UPSTREAM in pull_request.labels,
            pull_request.mergeable_state,
            snapshot,
        )

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
            problems.append(str(CountedThing.UNRESOLVED_THREAD.counted(unresolved)))
        return problems

    def line(self, checked_out: str) -> ReportLine:
        """
        :param checked_out: The branch the session works on.
        :return: The pull request in one line, without the workflow's prefix, yellow
            when something asks for attention.
        """
        marks = ["this branch"] if self.branch == checked_out else []
        marks += self.problems or ["ok"]
        tags = " · ".join(marks)
        return ReportLine(
            f"{NumberLink(self.number, self.url).markdown()} {self.title} - {tags}",
            Tone.ACTION if self.problems else Tone.NEWS,
            emphases=(Emphasis(f"- {tags}", Highlight.STATUS),),
        )


class PullRequestGroup(StrEnum):
    """
    The groups the session start lists open pull requests in, in the order shown, each
    member's value its heading.
    """

    OPENED_UPSTREAM = "pull requests open upstream"
    """
    Opened on the upstream repository, whether a draft here or not.
    """

    DRAFT = "draft pull requests"
    """
    Drafts not opened upstream.
    """

    READY = "pull requests ready for review"
    """
    Neither drafts nor opened upstream.
    """

    @classmethod
    def from_signals(cls, signals: PullRequestSignals) -> PullRequestGroup:
        """
        :param signals: An open pull request.
        :return: The group it is listed in.
        """
        if signals.opened_upstream:
            return cls.OPENED_UPSTREAM
        return cls.DRAFT if signals.draft else cls.READY


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

    def signals(self, number: int) -> PullRequestSignals:
        """
        :param number: An open pull request.
        :return: What in it asks for attention.
        """
        with ThreadPoolExecutor() as pool:
            pull_request = pool.submit(self.pull_requests.pull_request, number)
            snapshot = pool.submit(self.reviews.read_current_state, number)
        return PullRequestSignals.from_reads(pull_request.result(), snapshot.result())


# %% the section


@dataclass(frozen=True)
class PullRequestOverview(ReportSection):
    """
    The open pull requests the person has not shelved, one line each under their
    :class:`PullRequestGroup`, and how many wait on the person's review.
    """

    pull_requests: PullRequestTracker
    """
    Lists and reads the pull requests, creates the shelving label for the person to pick
    where the repository lacks it, and counts those waiting on the person's review.
    """

    reviews: PullRequestSource
    """
    Reads the pull requests' checks and review threads.
    """

    checked_out: str
    """
    The branch the session works on.
    """

    def lines(self) -> list[ReportLine]:
        with ThreadPoolExecutor() as pool:
            counted = pool.submit(self.pull_requests.awaiting_my_review)
            created = pool.submit(
                self.pull_requests.create_missing_labels, [PullRequestLabel.SHELVED]
            )
            numbers = [
                pull_request.number
                for pull_request in self.pull_requests.open_pull_requests()
                if PullRequestLabel.SHELVED not in pull_request.labels
            ]
            reader = PullRequestSignalReader(self.pull_requests, self.reviews)
            read = list(pool.map(reader.signals, numbers))
        created.result()
        grouped: dict[PullRequestGroup, list[ReportLine]] = {
            group: [] for group in PullRequestGroup
        }
        for signals in read:
            grouped[PullRequestGroup.from_signals(signals)].append(
                signals.line(self.checked_out)
            )
        lines = [
            line
            for group, items in grouped.items()
            for line in ReportGroup(group, items).lines()
        ]
        waiting = counted.result()
        if waiting:
            requests = CountedThing.WAITING_PULL_REQUEST.counted(waiting)
            lines.append(
                ReportLine(
                    Speaker.WORKFLOW.says(f"{requests} on your review"), Tone.ACTION
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
