"""
Tests for :mod:`github_workflow.label_events`: a stage, priority or evidence label
picked on GitHub replaces the others of its kind, and the Actions workflow running that
is written into a checkout.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from basstler_domain_model.github.issue_models import Issue, LabelEvent
from basstler_domain_model.github.repository_client import IssueLabelHistory
from basstler_domain_model.github.vocabulary import IssueState, IssueStateReason
from basstler_domain_model.locations import PathEnumeration
from basstler_domain_model.repository import Repository

from github_workflow import label_events
from github_workflow.workflow_templates import ActionPlaceholder
from github_workflow.findings import Evidence, FindingLabel, FindingStage, Priority
from github_workflow.label_events import (
    FindingAutomation,
    FindingLabelCompletion,
    IssueLabelled,
    LabelsCompletedReport,
    PickedLabelCompletion,
)
from github_workflow.workflow_templates import ActionRequirement
from github_workflow.report_lines import ReportLine, Tone
from github_workflow.locations import ProjectFile
from github_workflow.report_section import ReportSection

from .issues_in_memory import IssuesInMemory, finding, labelled_board

# %% the dataset


class LabelEventDataset(PathEnumeration):
    """
    Events GitHub hands an Actions workflow.
    """

    ISSUE_LABELLED = (
        Path(__file__).parent / "dataset" / "events" / "issue_labelled.json"
    )
    """
    A shelved label added to an unreviewed finding.
    """


def labelled(issue: Issue, label: str) -> Issue:
    """:param issue: An issue.
    :param label: A label just added to it.
    :return: The issue carrying it too."""
    return Issue(issue.number, issue.title, (*issue.labels, label), issue.state)


def board_with(issue: Issue) -> IssuesInMemory:
    """:param issue: The one issue on the board.
    :return: A board carrying every finding label already."""
    return IssuesInMemory({issue.number: issue}, set(FindingLabel.every_label))


# %% the event


def test_the_labelled_issue_and_label_are_read_from_the_event():
    data = json.loads(LabelEventDataset.ISSUE_LABELLED.value.read_text())

    event = IssueLabelled.from_json(data)

    assert event == IssueLabelled(
        Repository.parse(data["repository"]["full_name"]),
        data["issue"]["number"],
        data["label"]["name"],
    )


# %% completing a label change


def test_a_picked_stage_replaces_the_previous_stage():
    issue = labelled(
        finding(1, FindingStage.UNREVIEWED, Priority.LOW), FindingStage.SHELVED
    )
    board = board_with(issue)

    FindingLabelCompletion(board, board, 1, FindingStage.SHELVED).run()

    assert board.writes == [f"remove_label 1 {FindingStage.UNREVIEWED}"]


def test_a_picked_incorrect_stage_closes_the_finding_as_not_planned():
    issue = labelled(
        finding(1, FindingStage.ACCEPTED, Priority.LOW), FindingStage.INCORRECT
    )
    board = board_with(issue)

    FindingLabelCompletion(board, board, 1, FindingStage.INCORRECT).run()

    assert board.writes == [
        f"remove_label 1 {FindingStage.ACCEPTED}",
        f"close_issue 1 {IssueStateReason.NOT_PLANNED}",
    ]


def test_a_picked_priority_replaces_the_previous_priority():
    issue = labelled(finding(1, FindingStage.ACCEPTED, Priority.LOW), Priority.HIGH)
    board = board_with(issue)

    FindingLabelCompletion(board, board, 1, Priority.HIGH).run()

    assert board.writes == [f"remove_label 1 {Priority.LOW}"]


def test_a_priority_picked_on_a_plain_issue_makes_it_an_unreviewed_finding():
    issue = Issue(1, "An issue", ("bug", Priority.MEDIUM), IssueState.OPEN)
    board = board_with(issue)

    FindingLabelCompletion(board, board, 1, Priority.MEDIUM).run()

    assert board.writes == [f"add_labels 1 {[FindingStage.UNREVIEWED]}"]


def test_picked_evidence_replaces_the_previous_evidence():
    unproven = labelled(
        finding(1, FindingStage.ACCEPTED, Priority.LOW), Evidence.UNPROVEN
    )
    board = board_with(labelled(unproven, Evidence.PROVEN))

    FindingLabelCompletion(board, board, 1, Evidence.PROVEN).run()

    assert board.writes == [f"remove_label 1 {Evidence.UNPROVEN}"]


def test_a_label_removed_again_since_changes_nothing():
    board = board_with(finding(1, FindingStage.UNREVIEWED, Priority.LOW))

    FindingLabelCompletion(board, board, 1, FindingStage.SHELVED).run()

    assert board.writes == []


def test_a_label_outside_the_findings_changes_nothing():
    issue = labelled(finding(1, FindingStage.UNREVIEWED, Priority.LOW), "bug")
    board = board_with(issue)

    FindingLabelCompletion(board, board, 1, "bug").run()

    assert board.writes == []


# %% the Actions workflow


def test_the_actions_workflow_is_written_into_the_checkout_filled_in(tmp_path: Path):
    FindingAutomation(tmp_path).run()

    workflow = (tmp_path / ProjectFile.LABEL_COMPLETION_WORKFLOW.value).read_text()
    assert [p for p in ActionPlaceholder if p in workflow] == []
    assert all(requirement in workflow for requirement in ActionRequirement)
    assert f"python -m {label_events.__name__}" in workflow


# %% completing picked labels from a session


@dataclass(frozen=True)
class LabelsAddedInMemory(IssueLabelHistory):
    """
    Each issue's labels, added in the order given, none ever removed.
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
    return PickedLabelCompletion(board, board, LabelsAddedInMemory(added))


def with_labels(*labels: str) -> Issue:
    """
    :param labels: The labels it carries.
    :return: Open issue 1, carrying them.
    """
    return Issue(1, "Finding 1", labels, IssueState.OPEN)


def test_the_stage_added_last_replaces_the_one_before_it():
    board = labelled_board(
        with_labels(FindingStage.UNREVIEWED, Priority.MEDIUM, FindingStage.ACCEPTED)
    )

    completion(
        board, {1: [FindingStage.UNREVIEWED, Priority.MEDIUM, FindingStage.ACCEPTED]}
    ).complete()

    assert board.writes == [f"remove_label 1 {FindingStage.UNREVIEWED}"]


def test_the_priority_added_last_replaces_the_one_before_it():
    board = labelled_board(
        with_labels(FindingStage.ACCEPTED, Priority.HIGH, Priority.LOW)
    )

    completion(
        board, {1: [FindingStage.ACCEPTED, Priority.LOW, Priority.HIGH]}
    ).complete()

    assert board.writes == [f"remove_label 1 {Priority.LOW}"]


def test_an_open_incorrect_finding_is_closed():
    board = labelled_board(with_labels(FindingStage.INCORRECT, Priority.LOW))

    completion(board, {}).complete()

    assert f"close_issue 1 {IssueStateReason.NOT_PLANNED}" in board.writes


def test_a_finding_with_one_label_of_each_kind_is_left_as_it_is():
    board = labelled_board(finding(1, FindingStage.ACCEPTED, Priority.LOW))

    assert completion(board, {}).complete() == []
    assert board.writes == []


def test_the_session_start_says_what_was_completed_first():
    board = labelled_board(with_labels(FindingStage.INCORRECT, Priority.LOW))

    [line] = LabelsCompletedReport(completion(board, {}), NothingToSay()).lines()

    assert line.tone is Tone.NEWS
