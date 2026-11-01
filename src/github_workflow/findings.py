"""
Findings: what a session notices outside the work it is doing, kept as GitHub issues
rather than acted on.

Filed as unreviewed with a priority; only the person accepts or rejects them.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import ReprEnum

from basstler_domain_model.github.issue_models import Issue
from basstler_domain_model.github.labels import GitHubLabel, LabelWrite
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


class FindingStage(FindingLabel):
    """
    Where a finding stands; a rejected finding is a closed issue instead.
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

    @classmethod
    def of(cls, issue: Issue) -> Priority | None:
        """
        :param issue: An issue.
        :return: Its priority, ``None`` when it carries none.
        """
        return next((priority for priority in cls if priority in issue.labels), None)


# %% filing and listing


@dataclass(frozen=True)
class FindingFiling(WorkflowStep):
    """
    A finding filed as an unreviewed issue with its priority, creating the labels the
    repository lacks.
    """

    board: IssueBoard
    """
    Files the issue.
    """

    labels: RepositoryLabels
    """
    Lists and creates the repository's labels.
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
        present = self.labels.labels()
        for label in [*FindingStage, *Priority]:
            if label not in present:
                self.labels.create_label(label)
        number = self.board.open_issue(
            self.title, self.body, [FindingStage.UNREVIEWED, self.priority]
        )
        return f"filed finding #{number} ({self.priority.level})"


@dataclass(frozen=True)
class FindingListing(WorkflowStep):
    """
    The open findings, unreviewed first, most urgent first.
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


# %% the person's decisions


@dataclass(frozen=True)
class FindingAcceptance(WorkflowStep):
    """
    An unreviewed finding accepted, on the person's word.
    """

    board: IssueBoard
    """
    Relabels the issue.
    """

    number: int
    """
    The finding.
    """

    def run(self) -> str:
        unreviewed = self.board.issues([FindingStage.UNREVIEWED], IssueState.OPEN)
        issue = next(
            (issue for issue in unreviewed if issue.number == self.number), None
        )
        if issue is None:
            raise NotAFindingError(self.number)
        write = LabelWrite.replacing(
            issue.labels,
            added=[FindingStage.ACCEPTED],
            removed=[FindingStage.UNREVIEWED],
        )
        self.board.replace_labels(self.number, write.labels)
        return f"accepted finding #{self.number}"


@dataclass(frozen=True)
class FindingRejection(WorkflowStep):
    """
    A finding rejected, on the person's word: the reason commented, the issue closed as
    not planned, so later sessions do not raise it again.
    """

    board: IssueBoard
    """
    Comments on and closes the issue.
    """

    number: int
    """
    The finding.
    """

    reason: str
    """
    Why it is rejected.
    """

    def run(self) -> str:
        open_findings = [
            issue.number
            for stage in FindingStage
            for issue in self.board.issues([stage], IssueState.OPEN)
        ]
        if self.number not in open_findings:
            raise NotAFindingError(self.number)
        self.board.add_comment(self.number, f"Rejected: {self.reason}")
        self.board.close_issue(self.number, IssueStateReason.NOT_PLANNED)
        return f"rejected finding #{self.number}"


# %% the section


@dataclass(frozen=True)
class FindingsSummary(ReportSection):
    """
    How many findings wait for the person, by priority, and how many are accepted.
    """

    board: IssueBoard
    """
    Lists the issues.
    """

    def lines(self) -> list[ReportLine]:
        unreviewed = self.board.issues([FindingStage.UNREVIEWED], IssueState.OPEN)
        accepted = self.board.issues([FindingStage.ACCEPTED], IssueState.OPEN)
        if not unreviewed and not accepted:
            return []
        counted = Counter(Priority.of(issue) for issue in unreviewed)
        by_priority = ", ".join(
            f"{counted[priority]} {priority.level}"
            for priority in Priority
            if counted[priority]
        )
        detail = f" ({by_priority})" if by_priority else ""
        return [
            ReportLine(
                f"github-workflow: findings: {len(unreviewed)} unreviewed{detail}, "
                f"{len(accepted)} accepted",
                Tone.ACTION if unreviewed else Tone.NEWS,
            )
        ]
