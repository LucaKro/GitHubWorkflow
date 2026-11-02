"""
Findings: what a session notices outside the work it is doing, kept as GitHub issues
rather than acted on.

Filed or prioritized as unreviewed with a priority; only the person accepts, shelves or
rejects them.
"""

from __future__ import annotations

from abc import ABC
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from enum import ReprEnum
from typing import Self

from basstler_domain_model.github.issue_models import Issue
from basstler_domain_model.github.labels import GitHubLabel
from basstler_domain_model.github.repository_client import (
    IssueBoard,
    RepositoryLabels,
)
from basstler_domain_model.github.vocabulary import IssueState, IssueStateReason

from github_workflow.exceptions import NotAFindingError
from github_workflow.hooks import ReportLine, Tone
from github_workflow.report_section import ReportSection
from github_workflow.work import WorkflowStep

# %% the labels


class FindingLabel(GitHubLabel, ReprEnum):
    """
    The base of the labels a finding carries: each its own name, with what it means and
    its colour.
    """

    def __new__(cls, label: str, description: str, color: str) -> FindingLabel:
        """
        :param label: The label's name, as GitHub stores it.
        :param description: What it means, which it is created with.
        :param color: Its colour, as six hexadecimal digits.
        :return: The member.
        """
        member = str.__new__(cls, label)
        member._value_ = label
        member.description = description
        member.color = color
        return member

    @classmethod
    def of(cls, issue: Issue) -> Self | None:
        """
        :param issue: An issue.
        :return: The first of these labels it carries, ``None`` when it carries none.
        """
        return next((label for label in cls if label in issue.labels), None)


class FindingStage(FindingLabel):
    """
    Where a finding stands; an incorrect finding is also closed.
    """

    UNREVIEWED = (
        "finding: unreviewed",
        "Noticed while working on something else; not looked at yet",
        "fbca04",
    )
    """
    Filed by a session, waiting for the person.
    """

    ACCEPTED = (
        "finding: accepted",
        "Confirmed; working on it starts with a failing test",
        "0e8a16",
    )
    """
    Confirmed by the person.
    """

    SHELVED = ("finding: shelved", "Set aside for now; stays open", "d4c5f9")
    """
    Set aside by the person, apart from the findings waiting on them or on work.
    """

    INCORRECT = (
        "finding: incorrect",
        "Rejected as incorrect; closed as not planned",
        "e4e669",
    )
    """
    Rejected by the person, and closed.
    """


class Priority(FindingLabel):
    """
    How urgent a finding is, as the session that files it judges.
    """

    CRITICAL = (
        "priority: critical",
        "Breaks the default branch, security, or data",
        "b60205",
    )
    """
    Breaks the default branch, security, or data.
    """

    HIGH = ("priority: high", "Wrong behaviour in normal use", "d93f0b")
    """
    Wrong behaviour in normal use.
    """

    MEDIUM = (
        "priority: medium",
        "Wrong in edge cases, or a maintainability risk",
        "fbca04",
    )
    """
    Wrong in edge cases, or a maintainability risk.
    """

    LOW = ("priority: low", "Cosmetic, or cleanup", "c5def5")
    """
    Cosmetic, or cleanup.
    """

    @property
    def level(self) -> str:
        """:return: The priority's level alone, as the command line takes it."""
        return self._name_.lower()

    @classmethod
    def guide(cls) -> str:
        """:return: What each priority means, in one line."""
        return "; ".join(
            f"{priority.level}: {priority.description}" for priority in cls
        )


# %% labelling issues as findings


@dataclass(frozen=True)
class FindingLabelling(WorkflowStep, ABC):
    """
    A write that labels an issue as a finding, creating the finding labels the
    repository lacks.
    """

    board: IssueBoard
    """
    Writes the issue.
    """

    labels: RepositoryLabels
    """
    Lists and creates the repository's labels.
    """

    def create_missing_labels(self) -> None:
        """
        Create every stage and priority label the repository does not carry yet.
        """
        present = self.labels.labels()
        for label in [*FindingStage, *Priority]:
            if label not in present:
                self.labels.create_label(label)

    def relabel(self, issue: Issue, labels: Sequence[FindingLabel]) -> None:
        """
        Give an issue these labels, removing every other label of their kinds it
        carries.

        :param issue: The issue as it is labelled now.
        :param labels: At most one stage and one priority.
        """
        self.create_missing_labels()
        added = [label for label in labels if label not in issue.labels]
        if added:
            self.board.add_labels(issue.number, added)
        for label in labels:
            for replaced in type(label):
                if replaced not in labels and replaced in issue.labels:
                    self.board.remove_label(issue.number, replaced)


# %% filing and listing


@dataclass(frozen=True)
class FindingFiling(FindingLabelling):
    """
    A finding filed as an unreviewed issue with its priority.
    """

    title: str
    """
    The finding's title.
    """

    body: str
    """
    What was found, and where.
    """

    priority: Priority
    """
    How urgent it is.
    """

    def run(self) -> str:
        self.create_missing_labels()
        number = self.board.open_issue(
            self.title, self.body, [FindingStage.UNREVIEWED, self.priority]
        )
        return f"filed finding #{number} ({self.priority.level})"


@dataclass(frozen=True)
class FindingListing(WorkflowStep):
    """
    The open findings, unreviewed first and shelved last, most urgent first.
    """

    board: IssueBoard
    """
    Lists the issues.
    """

    def run(self) -> str:
        """
        :return: One finding per line; overrides :meth:`WorkflowStep.run`, which
            reports in one line.
        """
        lines = []
        for stage in FindingStage:
            for issue in sorted(
                self.board.issues([stage], IssueState.OPEN),
                key=lambda issue: list(Priority).index(
                    Priority.of(issue) or Priority.LOW
                ),
            ):
                priority = Priority.of(issue)
                level = priority.level if priority else "no priority"
                lines.append(f"#{issue.number} [{level}] {issue.title} ({stage})")
        return "\n".join(lines) or "no open findings"


# %% prioritizing


@dataclass(frozen=True)
class FindingPrioritization(FindingLabelling):
    """
    An existing issue given a priority, replacing any other it carries, and made an
    unreviewed finding when it carries no stage yet.
    """

    number: int
    """
    The issue.
    """

    priority: Priority
    """
    How urgent it is.
    """

    def run(self) -> str:
        issue = self.board.issue(self.number)
        stage = [] if FindingStage.of(issue) else [FindingStage.UNREVIEWED]
        self.relabel(issue, [self.priority, *stage])
        return f"prioritized #{self.number} as {self.priority.level}"


# %% the person's decisions


@dataclass(frozen=True)
class FindingDecision(FindingLabelling, ABC):
    """
    A finding moved to another stage, on the person's word.
    """

    number: int
    """
    The finding.
    """

    def open_finding(self, stages: Sequence[FindingStage]) -> Issue:
        """
        :param stages: The stages the decision moves a finding out of.
        :return: The finding, open in one of them.
        :raises NotAFindingError: If it is no open finding in one of them.
        """
        issue = self.board.issue(self.number)
        if issue.state is not IssueState.OPEN or FindingStage.of(issue) not in stages:
            raise NotAFindingError(self.number)
        return issue


@dataclass(frozen=True)
class FindingAcceptance(FindingDecision):
    """
    An unreviewed or shelved finding accepted.
    """

    def run(self) -> str:
        issue = self.open_finding([FindingStage.UNREVIEWED, FindingStage.SHELVED])
        self.relabel(issue, [FindingStage.ACCEPTED])
        return f"accepted finding #{self.number}"


@dataclass(frozen=True)
class FindingShelving(FindingDecision):
    """
    An unreviewed or accepted finding set aside, left open.
    """

    def run(self) -> str:
        issue = self.open_finding([FindingStage.UNREVIEWED, FindingStage.ACCEPTED])
        self.relabel(issue, [FindingStage.SHELVED])
        return f"shelved finding #{self.number}"


@dataclass(frozen=True)
class FindingRejection(FindingDecision):
    """
    An open finding rejected: marked incorrect, the reason commented, the issue closed
    as not planned, so later sessions do not raise it again.
    """

    reason: str
    """
    Why it is rejected.
    """

    def run(self) -> str:
        issue = self.open_finding(
            [FindingStage.UNREVIEWED, FindingStage.ACCEPTED, FindingStage.SHELVED]
        )
        self.relabel(issue, [FindingStage.INCORRECT])
        self.board.add_comment(self.number, f"Rejected: {self.reason}")
        self.board.close_issue(self.number, IssueStateReason.NOT_PLANNED)
        return f"rejected finding #{self.number}"


# %% the section


@dataclass(frozen=True)
class FindingsSummary(ReportSection):
    """
    How many findings wait for the person, by priority, how many are accepted, and how
    many are shelved.
    """

    board: IssueBoard
    """
    Lists the issues.
    """

    def lines(self) -> list[ReportLine]:
        unreviewed = self.board.issues([FindingStage.UNREVIEWED], IssueState.OPEN)
        accepted = self.board.issues([FindingStage.ACCEPTED], IssueState.OPEN)
        shelved = self.board.issues([FindingStage.SHELVED], IssueState.OPEN)
        if not unreviewed and not accepted and not shelved:
            return []
        counted = Counter(Priority.of(issue) for issue in unreviewed)
        by_priority = ", ".join(
            f"{counted[priority]} {priority.level}"
            for priority in Priority
            if counted[priority]
        )
        detail = f" ({by_priority})" if by_priority else ""
        set_aside = f", {len(shelved)} shelved" if shelved else ""
        return [
            ReportLine(
                f"github-workflow: findings: {len(unreviewed)} unreviewed{detail}, "
                f"{len(accepted)} accepted{set_aside}",
                Tone.ACTION if unreviewed else Tone.NEWS,
            )
        ]
