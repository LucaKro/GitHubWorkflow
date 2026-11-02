"""
Tests for :mod:`github_workflow.findings`: findings are filed or prioritized as
unreviewed with a priority, listed most urgent first, and moved on only by the person's
accept, shelve or reject.
"""

from __future__ import annotations

import pytest

from basstler_domain_model.github.issue_models import Issue
from basstler_domain_model.github.vocabulary import IssueState, IssueStateReason

from github_workflow.exceptions import NotAFindingError
from github_workflow.findings import (
    FindingAcceptance,
    FindingFiling,
    FindingListing,
    FindingPrioritization,
    FindingRejection,
    FindingShelving,
    FindingsSummary,
    FindingStage,
    Priority,
)
from github_workflow.hooks import Tone

from .issues_in_memory import IssuesInMemory, finding

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


def test_shelved_findings_are_listed_after_the_accepted():
    board = IssuesInMemory(
        {
            1: finding(1, FindingStage.SHELVED, Priority.CRITICAL),
            2: finding(2, FindingStage.ACCEPTED, Priority.LOW),
        }
    )

    listed = FindingListing(board).run().splitlines()

    assert [line.split()[0] for line in listed] == ["#2", "#1"]


# %% the person's decisions


def test_an_accepted_finding_keeps_its_priority():
    board = IssuesInMemory(
        {1: finding(1, FindingStage.UNREVIEWED, Priority.MEDIUM)},
        {*FindingStage, *Priority},
    )

    FindingAcceptance(board, board, 1).run()

    assert board.writes == [
        f"add_labels 1 {[FindingStage.ACCEPTED]}",
        f"remove_label 1 {FindingStage.UNREVIEWED}",
    ]


def test_a_shelved_finding_can_be_accepted():
    board = IssuesInMemory(
        {1: finding(1, FindingStage.SHELVED, Priority.MEDIUM)},
        {*FindingStage, *Priority},
    )

    FindingAcceptance(board, board, 1).run()

    assert board.writes == [
        f"add_labels 1 {[FindingStage.ACCEPTED]}",
        f"remove_label 1 {FindingStage.SHELVED}",
    ]


def test_accepting_what_is_no_unreviewed_finding_is_refused():
    board = IssuesInMemory({1: finding(1, FindingStage.ACCEPTED, Priority.MEDIUM)})

    with pytest.raises(NotAFindingError):
        FindingAcceptance(board, board, 1).run()

    assert board.writes == []


def test_a_shelved_finding_stays_open_with_its_priority():
    board = IssuesInMemory(
        {1: finding(1, FindingStage.ACCEPTED, Priority.HIGH)},
        {*FindingStage, *Priority},
    )

    FindingShelving(board, board, 1).run()

    assert board.writes == [
        f"add_labels 1 {[FindingStage.SHELVED]}",
        f"remove_label 1 {FindingStage.ACCEPTED}",
    ]


def test_shelving_what_is_no_finding_is_refused():
    board = IssuesInMemory({1: Issue(1, "An issue", ("bug",), IssueState.OPEN)})

    with pytest.raises(NotAFindingError):
        FindingShelving(board, board, 1).run()

    assert board.writes == []


def test_a_rejected_finding_is_marked_incorrect_and_closed_with_its_reason():
    board = IssuesInMemory(
        {1: finding(1, FindingStage.UNREVIEWED, Priority.LOW)},
        {*FindingStage, *Priority},
    )

    FindingRejection(board, board, 1, "Intended behaviour").run()

    assert board.writes == [
        f"add_labels 1 {[FindingStage.INCORRECT]}",
        f"remove_label 1 {FindingStage.UNREVIEWED}",
        "add_comment 1 Rejected: Intended behaviour",
        f"close_issue 1 {IssueStateReason.NOT_PLANNED}",
    ]


def test_rejecting_a_closed_finding_is_refused():
    board = IssuesInMemory(
        {1: Issue(1, "Finding 1", (FindingStage.ACCEPTED,), IssueState.CLOSED)}
    )

    with pytest.raises(NotAFindingError):
        FindingRejection(board, board, 1, "Done already").run()

    assert board.writes == []


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


def test_the_summary_counts_shelved_findings_apart():
    board = IssuesInMemory(
        {
            1: finding(1, FindingStage.UNREVIEWED, Priority.LOW),
            2: finding(2, FindingStage.SHELVED, Priority.HIGH),
        }
    )

    [line] = FindingsSummary(board).lines()

    assert line.text == (
        "github-workflow: findings: 1 unreviewed (1 low), 0 accepted, 1 shelved"
    )


def test_a_repository_without_findings_says_nothing():
    assert FindingsSummary(IssuesInMemory()).lines() == []
