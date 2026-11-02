"""
Tests for :mod:`github_workflow.findings`: findings are filed or prioritized as
unreviewed with a priority, listed most urgent first, and moved on only by the person's
accept or reject.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import pytest

from basstler_domain_model.github.issue_models import Issue
from basstler_domain_model.github.labels import GitHubLabel
from basstler_domain_model.github.repository_client import (
    IssueBoard,
    RepositoryLabels,
)
from basstler_domain_model.github.vocabulary import IssueState, IssueStateReason

from github_workflow.exceptions import NotAFindingError
from github_workflow.findings import (
    FindingAcceptance,
    FindingFiling,
    FindingListing,
    FindingPrioritization,
    FindingRejection,
    FindingsSummary,
    FindingStage,
    Priority,
)
from github_workflow.hooks import Tone

# %% an issue board in memory


@dataclass(frozen=True)
class IssuesInMemory(IssueBoard, RepositoryLabels):
    """
    A repository's issues and labels, recording every write.
    """

    open_issues: dict[int, Issue] = field(default_factory=dict)
    """
    The open issues, by number.
    """

    present_labels: set[str] = field(default_factory=set)
    """
    The labels the repository carries.
    """

    writes: list[str] = field(default_factory=list)
    """
    Every write, in a word and its arguments.
    """

    def labels(self) -> set[str]:
        return set(self.present_labels)

    def create_label(self, label: GitHubLabel) -> None:
        self.writes.append(f"create_label {label}")
        self.present_labels.add(label)

    def open_issue(self, title: str, body: str, labels: Sequence[str]) -> int:
        number = max(self.open_issues, default=0) + 1
        self.open_issues[number] = Issue(number, title, tuple(labels), IssueState.OPEN)
        self.writes.append(f"open_issue {number} {list(labels)}")
        return number

    def issues(self, labels: Sequence[str], state: IssueState) -> list[Issue]:
        return [
            issue
            for issue in self.open_issues.values()
            if issue.state is state and all(label in issue.labels for label in labels)
        ]

    def issue(self, number: int) -> Issue:
        return self.open_issues[number]

    def replace_labels(self, number: int, labels: Sequence[str]) -> None:
        self.writes.append(f"replace_labels {number} {list(labels)}")

    def add_labels(self, number: int, labels: Sequence[str]) -> None:
        self.writes.append(f"add_labels {number} {list(labels)}")

    def remove_label(self, number: int, label: str) -> None:
        self.writes.append(f"remove_label {number} {label}")

    def add_comment(self, number: int, body: str) -> str:
        self.writes.append(f"add_comment {number} {body}")
        return ""

    def close_issue(self, number: int, reason: IssueStateReason) -> None:
        self.writes.append(f"close_issue {number} {reason}")


def finding(number: int, stage: FindingStage, priority: Priority) -> Issue:
    """:param number: The issue's number.
    :param stage: Where the finding stands.
    :param priority: How urgent it is.
    :return: The finding as an open issue."""
    return Issue(number, f"Finding {number}", (stage, priority), IssueState.OPEN)


# %% filing


def test_a_finding_is_filed_unreviewed_with_its_priority_and_every_label_created():
    board = IssuesInMemory()

    FindingFiling(board, board, "A title", "A body", Priority.HIGH).run()

    created = [f"create_label {label}" for label in [*FindingStage, *Priority]]
    assert board.writes == created + [
        f"open_issue 1 {[FindingStage.UNREVIEWED, Priority.HIGH]}"
    ]


def test_labels_the_repository_has_are_not_created_again():
    board = IssuesInMemory(present_labels={*FindingStage, *Priority})

    FindingFiling(board, board, "A title", "A body", Priority.LOW).run()

    assert board.writes == [f"open_issue 1 {[FindingStage.UNREVIEWED, Priority.LOW]}"]


# %% prioritizing


def test_an_issue_without_a_stage_is_prioritized_as_an_unreviewed_finding():
    board = IssuesInMemory(
        {1: Issue(1, "An issue", ("bug",), IssueState.OPEN)},
        {*FindingStage, *Priority},
    )

    FindingPrioritization(board, board, 1, Priority.HIGH).run()

    assert board.writes == [f"add_labels 1 {[Priority.HIGH, FindingStage.UNREVIEWED]}"]


def test_a_new_priority_replaces_the_old_one_and_keeps_the_stage():
    board = IssuesInMemory(
        {1: finding(1, FindingStage.ACCEPTED, Priority.LOW)},
        {*FindingStage, *Priority},
    )

    FindingPrioritization(board, board, 1, Priority.MEDIUM).run()

    assert board.writes == [
        f"add_labels 1 {[Priority.MEDIUM]}",
        f"remove_label 1 {Priority.LOW}",
    ]


def test_the_priority_a_finding_already_has_writes_nothing():
    board = IssuesInMemory(
        {1: finding(1, FindingStage.UNREVIEWED, Priority.HIGH)},
        {*FindingStage, *Priority},
    )

    FindingPrioritization(board, board, 1, Priority.HIGH).run()

    assert board.writes == []


def test_prioritizing_creates_the_labels_the_repository_lacks():
    board = IssuesInMemory({1: Issue(1, "An issue", (), IssueState.OPEN)})

    FindingPrioritization(board, board, 1, Priority.LOW).run()

    created = [f"create_label {label}" for label in [*FindingStage, *Priority]]
    assert board.writes == created + [
        f"add_labels 1 {[Priority.LOW, FindingStage.UNREVIEWED]}"
    ]


# %% listing


def test_findings_are_listed_unreviewed_first_and_most_urgent_first():
    board = IssuesInMemory(
        {
            1: finding(1, FindingStage.ACCEPTED, Priority.CRITICAL),
            2: finding(2, FindingStage.UNREVIEWED, Priority.LOW),
            3: finding(3, FindingStage.UNREVIEWED, Priority.CRITICAL),
        }
    )

    listed = FindingListing(board).run().splitlines()

    assert [line.split()[0] for line in listed] == ["#3", "#2", "#1"]


# %% the person's decisions


def test_an_accepted_finding_keeps_its_priority():
    board = IssuesInMemory({1: finding(1, FindingStage.UNREVIEWED, Priority.MEDIUM)})

    FindingAcceptance(board, 1).run()

    assert board.writes == [
        f"replace_labels 1 {[Priority.MEDIUM, FindingStage.ACCEPTED]}"
    ]


def test_accepting_what_is_no_unreviewed_finding_is_refused():
    board = IssuesInMemory({1: finding(1, FindingStage.ACCEPTED, Priority.MEDIUM)})

    with pytest.raises(NotAFindingError):
        FindingAcceptance(board, 1).run()

    assert board.writes == []


def test_a_rejected_finding_is_closed_as_not_planned_with_its_reason():
    board = IssuesInMemory({1: finding(1, FindingStage.UNREVIEWED, Priority.LOW)})

    FindingRejection(board, 1, "Intended behaviour").run()

    assert board.writes == [
        "add_comment 1 Rejected: Intended behaviour",
        f"close_issue 1 {IssueStateReason.NOT_PLANNED}",
    ]


# %% the section


def test_the_summary_counts_unreviewed_findings_by_priority():
    board = IssuesInMemory(
        {
            1: finding(1, FindingStage.UNREVIEWED, Priority.CRITICAL),
            2: finding(2, FindingStage.UNREVIEWED, Priority.MEDIUM),
            3: finding(3, FindingStage.ACCEPTED, Priority.HIGH),
        }
    )

    [line] = FindingsSummary(board).lines()

    assert line.text == (
        "github-workflow: findings: 2 unreviewed (1 critical, 1 medium), 1 accepted"
    )
    assert line.tone is Tone.ACTION


def test_a_repository_without_findings_says_nothing():
    assert FindingsSummary(IssuesInMemory()).lines() == []
