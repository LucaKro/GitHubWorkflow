"""
Tests for :mod:`github_workflow.label_events`: a stage, priority or evidence label
picked on GitHub replaces the others of its kind, and the Actions workflow running that
is written into a checkout.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from domain_model.github.issue_models import Issue, LabelEvent
from domain_model.github.repository_client import IssueLabelTracker
from domain_model.github.vocabulary import IssueState, IssueStateReason

from github_workflow import label_events
from github_workflow.findings import Evidence, FindingLabel, FindingStage, Priority
from github_workflow.label_events import (
    FindingAutomation,
    FindingLabelCompletion,
    LabelsCompletedReport,
    PickedLabelCompletion,
)
from github_workflow.locations import ProjectFile
from github_workflow.report_lines import ReportLine, Tone
from github_workflow.report_section import ReportSection
from github_workflow.workflow_templates import ActionPlaceholder, ActionRequirement

from .issues_in_memory import IssuesInMemory, build_finding, labelled_board

# %% helpers


def add_label(issue: Issue, label: str) -> Issue:
    """:param issue: An issue.
    :param label: A label just added to it.
    :return: The issue carrying it too."""
    return Issue(issue.number, issue.title, (*issue.labels, label), issue.state)


def build_board(issue: Issue) -> IssuesInMemory:
    """:param issue: The one issue on the board.
    :return: A board carrying every finding label already."""
    return IssuesInMemory({issue.number: issue}, set(FindingLabel.every_label))


# %% completing a label change


def test_a_picked_stage_replaces_the_previous_stage() -> None:
    issue = add_label(
        build_finding(1, FindingStage.UNREVIEWED, Priority.LOW), FindingStage.SHELVED
    )
    board = build_board(issue)

    FindingLabelCompletion(board, 1, FindingStage.SHELVED).run()

    assert board.writes == [f"remove_label 1 {FindingStage.UNREVIEWED}"]


def test_a_picked_incorrect_stage_closes_the_finding_as_not_planned() -> None:
    issue = add_label(
        build_finding(1, FindingStage.ACCEPTED, Priority.LOW), FindingStage.INCORRECT
    )
    board = build_board(issue)

    FindingLabelCompletion(board, 1, FindingStage.INCORRECT).run()

    assert board.writes == [
        f"remove_label 1 {FindingStage.ACCEPTED}",
        f"close_issue 1 {IssueStateReason.NOT_PLANNED}",
    ]


def test_a_picked_priority_replaces_the_previous_priority() -> None:
    issue = add_label(
        build_finding(1, FindingStage.ACCEPTED, Priority.LOW), Priority.HIGH
    )
    board = build_board(issue)

    FindingLabelCompletion(board, 1, Priority.HIGH).run()

    assert board.writes == [f"remove_label 1 {Priority.LOW}"]


def test_a_priority_picked_on_a_plain_issue_makes_it_an_unreviewed_finding() -> None:
    issue = Issue(1, "An issue", ("bug", Priority.MEDIUM), IssueState.OPEN)
    board = build_board(issue)

    FindingLabelCompletion(board, 1, Priority.MEDIUM).run()

    assert board.writes == [f"add_labels 1 {[FindingStage.UNREVIEWED]}"]


def test_picked_evidence_replaces_the_previous_evidence() -> None:
    unproven = add_label(
        build_finding(1, FindingStage.ACCEPTED, Priority.LOW), Evidence.UNPROVEN
    )
    board = build_board(add_label(unproven, Evidence.PROVEN))

    FindingLabelCompletion(board, 1, Evidence.PROVEN).run()

    assert board.writes == [f"remove_label 1 {Evidence.UNPROVEN}"]


def test_a_label_removed_again_since_changes_nothing() -> None:
    board = build_board(build_finding(1, FindingStage.UNREVIEWED, Priority.LOW))

    FindingLabelCompletion(board, 1, FindingStage.SHELVED).run()

    assert board.writes == []


def test_a_label_outside_the_findings_changes_nothing() -> None:
    issue = add_label(build_finding(1, FindingStage.UNREVIEWED, Priority.LOW), "bug")
    board = build_board(issue)

    FindingLabelCompletion(board, 1, "bug").run()

    assert board.writes == []


# %% the Actions workflow


def test_the_actions_workflow_is_written_into_the_checkout_filled_in(
    tmp_path: Path,
) -> None:
    FindingAutomation(tmp_path).run()

    workflow = (tmp_path / ProjectFile.LABEL_COMPLETION_WORKFLOW.value).read_text()
    assert [p for p in ActionPlaceholder if p in workflow] == []
    assert all(requirement in workflow for requirement in ActionRequirement)
    assert f"python -m {label_events.__name__}" in workflow


# %% completing picked labels from a session


@dataclass(frozen=True)
class LabelsAddedInMemory(IssuesInMemory, IssueLabelTracker):
    """
    A repository's issues and labels, each issue's labels added in the order given, none
    ever removed.
    """

    added: dict[int, list[str]] = field(default_factory=dict)
    """
    The labels added to each issue, oldest first.
    """

    def label_events(self, number: int) -> list[LabelEvent]:
        return [LabelEvent(label, True) for label in self.added.get(number, [])]


@dataclass(frozen=True)
class NothingToSay(ReportSection):
    """
    A section with nothing to say.
    """

    def lines(self) -> list[ReportLine]:
        return []


def completion(
    board: IssuesInMemory, added: dict[int, list[str]]
) -> PickedLabelCompletion:
    """
    :param board: The findings.
    :param added: The labels added to each issue, oldest first.
    :return: Completes the labels picked on the board.
    """
    return PickedLabelCompletion(
        LabelsAddedInMemory(
            board.open_issues,
            board.present_labels,
            board.posted,
            board.author,
            board.writes,
            added=added,
        )
    )


def build_labelled_issue(*labels: str) -> Issue:
    """
    :param labels: The labels it carries.
    :return: Open issue 1, carrying them.
    """
    return Issue(1, "Finding 1", labels, IssueState.OPEN)


def test_the_stage_added_last_replaces_the_one_before_it() -> None:
    board = labelled_board(
        build_labelled_issue(
            FindingStage.UNREVIEWED, Priority.MEDIUM, FindingStage.ACCEPTED
        )
    )

    completion(
        board, {1: [FindingStage.UNREVIEWED, Priority.MEDIUM, FindingStage.ACCEPTED]}
    ).complete()

    assert board.writes == [f"remove_label 1 {FindingStage.UNREVIEWED}"]


def test_the_priority_added_last_replaces_the_one_before_it() -> None:
    board = labelled_board(
        build_labelled_issue(FindingStage.ACCEPTED, Priority.HIGH, Priority.LOW)
    )

    completion(
        board, {1: [FindingStage.ACCEPTED, Priority.LOW, Priority.HIGH]}
    ).complete()

    assert board.writes == [f"remove_label 1 {Priority.LOW}"]


def test_an_open_incorrect_finding_is_closed() -> None:
    board = labelled_board(build_labelled_issue(FindingStage.INCORRECT, Priority.LOW))

    completion(board, {}).complete()

    assert f"close_issue 1 {IssueStateReason.NOT_PLANNED}" in board.writes


def test_a_finding_with_one_label_of_each_kind_is_left_as_it_is() -> None:
    board = labelled_board(build_finding(1, FindingStage.ACCEPTED, Priority.LOW))

    assert completion(board, {}).complete() == []
    assert board.writes == []


def test_the_session_start_says_what_was_completed_first() -> None:
    board = labelled_board(build_labelled_issue(FindingStage.INCORRECT, Priority.LOW))

    [line] = LabelsCompletedReport(completion(board, {}), NothingToSay()).lines()

    assert line.tone is Tone.NEWS
