"""
Tests for :mod:`github_workflow.findings`: findings are filed or prioritized as
unreviewed with a priority, listed most urgent first, moved on only by the person's
accept, shelve or reject, proven by a test failing on the default branch, and worked on
in a draft only once accepted and proven.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from basstler_domain_model.github.issue_models import Issue, IssueComment
from basstler_domain_model.github.vocabulary import (
    ClosingKeyword,
    IssueState,
    IssueStateReason,
)

from github_workflow.exceptions import (
    AlreadyProvenError,
    BrokenTestError,
    FindingNotAcceptedError,
    MissingProofError,
    NotAFindingError,
    NothingToEditError,
    PassingTestError,
    ProofNoLongerHoldsError,
)
from github_workflow.findings import (
    Evidence,
    FindingAcceptance,
    FindingComment,
    FindingDraftOpening,
    FindingEdit,
    FindingFiling,
    FindingLabel,
    FindingListing,
    FindingPrioritization,
    FindingProving,
    FindingRecheck,
    FindingRejection,
    FindingShelving,
    FindingsSummary,
    FindingStage,
    FindingUnproving,
    Priority,
    ProvenFindingFiling,
)
from github_workflow.hooks import Tone
from github_workflow.policy import WritePolicy
from github_workflow.proofs import BranchTip, FindingTest, ProofAttempt, ProofOutcome
from github_workflow.settings import WorkflowSettings
from github_workflow.stacks import StackPlacement
from github_workflow.work import DraftOpening

from .issues_in_memory import (
    IssuesInMemory,
    PresetOutcomeRunner,
    finding,
    labelled_board,
)
from .stacked_pull_requests import DraftsAndStacksInMemory
from .test_work import work

# %% proofs


def finding_test() -> FindingTest:
    """:return: A test showing a finding."""
    return FindingTest(
        Path("tests/test_finding.py"), "def test_it():\n    assert False\n"
    )


def runner(outcome: ProofOutcome) -> PresetOutcomeRunner:
    """:param outcome: How every test fares.
    :return: A runner answering every test so."""
    message = "" if outcome is ProofOutcome.PASSES else "assert False"
    return PresetOutcomeRunner(
        ProofAttempt(
            finding_test(), BranchTip("main", "0123456789abcdef"), outcome, message
        )
    )


def proven(issue: Issue) -> Issue:
    """:param issue: A finding.
    :return: It, labelled proven too."""
    return Issue(
        issue.number, issue.title, (*issue.labels, Evidence.PROVEN), issue.state
    )


def with_proof_posted(board: IssuesInMemory, number: int, author: str) -> None:
    """
    Post the proof the failing runner makes on an issue.

    :param board: The board.
    :param number: The issue.
    :param author: Who posts it.
    """
    proof = runner(ProofOutcome.FAILS).outcome.proof()
    board.posted[number] = [IssueComment(author, proof.comment())]


# %% filing


def test_a_finding_is_filed_unreviewed_with_its_priority_and_every_label_created():
    board = IssuesInMemory()

    FindingFiling(board, board, "A title", "A body", Priority.HIGH).run()

    created = [f"create_label {label}" for label in FindingLabel.every_label]
    assert board.writes == created + [
        f"open_issue 1 {[FindingStage.UNREVIEWED, Priority.HIGH]}"
    ]


def test_labels_the_repository_has_are_not_created_again():
    board = IssuesInMemory(present_labels=set(FindingLabel.every_label))

    FindingFiling(board, board, "A title", "A body", Priority.LOW).run()

    assert board.writes == [f"open_issue 1 {[FindingStage.UNREVIEWED, Priority.LOW]}"]


def test_a_proven_finding_is_filed_unreviewed_and_proven_with_its_proof_posted():
    board = labelled_board()
    failing = runner(ProofOutcome.FAILS)

    ProvenFindingFiling(
        board, board, "A title", "A body", Priority.HIGH, finding_test(), failing
    ).run()

    assert board.writes == [
        f"open_issue 1 {[FindingStage.UNREVIEWED, Priority.HIGH, Evidence.PROVEN]}",
        f"add_comment 1 {failing.outcome.proof().comment()}",
    ]


@pytest.mark.parametrize(
    "outcome, error",
    [(ProofOutcome.PASSES, PassingTestError), (ProofOutcome.BROKEN, BrokenTestError)],
)
def test_a_finding_whose_test_does_not_fail_is_not_filed(
    outcome: ProofOutcome, error: type[Exception]
):
    board = labelled_board()

    with pytest.raises(error):
        ProvenFindingFiling(
            board,
            board,
            "A title",
            "A body",
            Priority.HIGH,
            finding_test(),
            runner(outcome),
        ).run()

    assert board.writes == []


# %% prioritizing


def test_an_issue_without_a_stage_is_prioritized_as_an_unreviewed_finding():
    board = IssuesInMemory(
        {1: Issue(1, "An issue", ("bug",), IssueState.OPEN)},
        set(FindingLabel.every_label),
    )

    FindingPrioritization(board, board, 1, Priority.HIGH).run()

    assert board.writes == [f"add_labels 1 {[Priority.HIGH, FindingStage.UNREVIEWED]}"]


def test_a_new_priority_replaces_the_old_one_and_keeps_the_stage():
    board = IssuesInMemory(
        {1: finding(1, FindingStage.ACCEPTED, Priority.LOW)},
        set(FindingLabel.every_label),
    )

    FindingPrioritization(board, board, 1, Priority.MEDIUM).run()

    assert board.writes == [
        f"add_labels 1 {[Priority.MEDIUM]}",
        f"remove_label 1 {Priority.LOW}",
    ]


def test_the_priority_a_finding_already_has_writes_nothing():
    board = IssuesInMemory(
        {1: finding(1, FindingStage.UNREVIEWED, Priority.HIGH)},
        set(FindingLabel.every_label),
    )

    FindingPrioritization(board, board, 1, Priority.HIGH).run()

    assert board.writes == []


def test_prioritizing_creates_the_labels_the_repository_lacks():
    board = IssuesInMemory({1: Issue(1, "An issue", (), IssueState.OPEN)})

    FindingPrioritization(board, board, 1, Priority.LOW).run()

    created = [f"create_label {label}" for label in FindingLabel.every_label]
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


def test_a_listed_finding_shows_its_evidence():
    board = IssuesInMemory({1: proven(finding(1, FindingStage.ACCEPTED, Priority.LOW))})

    listed = FindingListing(board).run()

    assert listed.endswith(f"({FindingStage.ACCEPTED}, {Evidence.PROVEN})")


# %% the person's decisions


def test_an_accepted_finding_keeps_its_priority():
    board = IssuesInMemory(
        {1: finding(1, FindingStage.UNREVIEWED, Priority.MEDIUM)},
        set(FindingLabel.every_label),
    )

    FindingAcceptance(board, board, 1).run()

    assert board.writes == [
        f"add_labels 1 {[FindingStage.ACCEPTED]}",
        f"remove_label 1 {FindingStage.UNREVIEWED}",
    ]


def test_a_shelved_finding_can_be_accepted():
    board = IssuesInMemory(
        {1: finding(1, FindingStage.SHELVED, Priority.MEDIUM)},
        set(FindingLabel.every_label),
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
        set(FindingLabel.every_label),
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
        set(FindingLabel.every_label),
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


# %% commenting and editing


def test_a_finding_is_commented_on():
    board = IssuesInMemory({1: finding(1, FindingStage.ACCEPTED, Priority.HIGH)})

    FindingComment(board, board, 1, "Found a second instance.").run()

    assert board.writes == ["add_comment 1 Found a second instance."]


def test_a_finding_s_title_and_text_are_rewritten():
    board = IssuesInMemory({1: finding(1, FindingStage.UNREVIEWED, Priority.LOW)})

    FindingEdit(board, board, 1, "A sharper title", "What was found, corrected.").run()

    assert board.writes == [
        "set_issue_title 1 A sharper title",
        "set_issue_description 1 What was found, corrected.",
    ]


def test_only_what_is_given_is_rewritten():
    board = IssuesInMemory({1: finding(1, FindingStage.UNREVIEWED, Priority.LOW)})

    FindingEdit(board, board, 1, None, "What was found, corrected.").run()

    assert board.writes == ["set_issue_description 1 What was found, corrected."]


def test_an_edit_changing_nothing_is_refused():
    board = IssuesInMemory({1: finding(1, FindingStage.UNREVIEWED, Priority.LOW)})

    with pytest.raises(NothingToEditError):
        FindingEdit(board, board, 1, None, None).run()

    assert board.writes == []


def test_a_closed_finding_is_neither_commented_on_nor_edited():
    board = IssuesInMemory(
        {1: Issue(1, "Finding 1", (FindingStage.INCORRECT,), IssueState.CLOSED)}
    )

    with pytest.raises(NotAFindingError):
        FindingComment(board, board, 1, "More").run()
    with pytest.raises(NotAFindingError):
        FindingEdit(board, board, 1, "A title", None).run()

    assert board.writes == []


# %% proving


def test_proving_posts_the_proof_and_labels_the_finding_proven():
    board = labelled_board(finding(1, FindingStage.ACCEPTED, Priority.HIGH))
    failing = runner(ProofOutcome.FAILS)

    FindingProving(board, board, 1, finding_test(), failing).run()

    assert board.writes == [
        f"add_comment 1 {failing.outcome.proof().comment()}",
        f"add_labels 1 {[Evidence.PROVEN]}",
    ]


def test_proving_an_unproven_finding_replaces_the_label():
    unproven = finding(1, FindingStage.UNREVIEWED, Priority.LOW)
    board = labelled_board(
        Issue(1, unproven.title, (*unproven.labels, Evidence.UNPROVEN), IssueState.OPEN)
    )
    failing = runner(ProofOutcome.FAILS)

    FindingProving(board, board, 1, finding_test(), failing).run()

    assert board.writes[1:] == [
        f"add_labels 1 {[Evidence.PROVEN]}",
        f"remove_label 1 {Evidence.UNPROVEN}",
    ]


def test_proving_with_a_test_that_does_not_fail_writes_nothing():
    board = labelled_board(finding(1, FindingStage.ACCEPTED, Priority.HIGH))

    with pytest.raises(PassingTestError):
        FindingProving(
            board, board, 1, finding_test(), runner(ProofOutcome.PASSES)
        ).run()

    assert board.writes == []


def test_proving_a_rejected_finding_is_refused_before_its_test_runs():
    rejected = finding(1, FindingStage.INCORRECT, Priority.HIGH)
    board = labelled_board(Issue(1, rejected.title, rejected.labels, IssueState.CLOSED))
    failing = runner(ProofOutcome.FAILS)

    with pytest.raises(NotAFindingError):
        FindingProving(board, board, 1, finding_test(), failing).run()

    assert failing.ran == []


def test_an_unprovable_finding_is_labelled_unproven_with_the_reason():
    board = labelled_board(finding(1, FindingStage.ACCEPTED, Priority.HIGH))

    FindingUnproving(board, board, 1, "Needs a live server").run()

    assert board.writes == [
        "add_comment 1 Unproven: Needs a live server",
        f"add_labels 1 {[Evidence.UNPROVEN]}",
    ]


def test_a_proven_finding_cannot_be_marked_unproven():
    board = labelled_board(proven(finding(1, FindingStage.ACCEPTED, Priority.HIGH)))

    with pytest.raises(AlreadyProvenError):
        FindingUnproving(board, board, 1, "Needs a live server").run()

    assert board.writes == []


# %% rechecking


def test_a_recheck_runs_the_posted_test_again_and_writes_nothing(
    settings: WorkflowSettings,
):
    board = labelled_board(proven(finding(1, FindingStage.ACCEPTED, Priority.HIGH)))
    with_proof_posted(board, 1, settings.owner)
    failing = runner(ProofOutcome.FAILS)

    FindingRecheck(board, failing, [settings.owner], 1).run()

    assert (failing.ran, board.writes) == ([finding_test()], [])


@pytest.mark.parametrize("outcome", [ProofOutcome.PASSES, ProofOutcome.BROKEN])
def test_a_proof_whose_test_no_longer_fails_is_reported(
    settings: WorkflowSettings, outcome: ProofOutcome
):
    board = labelled_board(proven(finding(1, FindingStage.ACCEPTED, Priority.HIGH)))
    with_proof_posted(board, 1, settings.owner)

    with pytest.raises(ProofNoLongerHoldsError):
        FindingRecheck(board, runner(outcome), [settings.owner], 1).run()


def test_a_finding_labelled_proven_without_a_posted_proof_cannot_be_rechecked(
    settings: WorkflowSettings,
):
    board = labelled_board(proven(finding(1, FindingStage.ACCEPTED, Priority.HIGH)))

    with pytest.raises(MissingProofError):
        FindingRecheck(board, runner(ProofOutcome.FAILS), [settings.owner], 1).run()


def test_a_posted_proof_on_a_finding_not_labelled_proven_is_not_rechecked(
    settings: WorkflowSettings,
):
    board = labelled_board(finding(1, FindingStage.ACCEPTED, Priority.HIGH))
    with_proof_posted(board, 1, settings.owner)

    with pytest.raises(MissingProofError):
        FindingRecheck(board, runner(ProofOutcome.FAILS), [settings.owner], 1).run()


# %% working on a finding


@dataclass(frozen=True)
class DescribedDraftsInMemory(DraftsAndStacksInMemory):
    """
    The stand-in, also keeping each draft's description.
    """

    descriptions: dict[int, str] = field(default_factory=dict)
    """
    Each draft's description, by number.
    """

    def open_draft(self, head: str, base: str, title: str, body: str) -> int:
        number = super().open_draft(head, base, title, body)
        self.descriptions[number] = body
        return number


def draft_for_finding(
    work: WritePolicy,
    github: DescribedDraftsInMemory,
    board: IssuesInMemory,
    outcome: ProofOutcome,
    settings: WorkflowSettings,
) -> FindingDraftOpening:
    """
    :param work: The rules of a checkout on a pushed work branch.
    :param github: The pull requests.
    :param board: The issues, finding #7 among them.
    :param outcome: How the finding's test fares when run again.
    :param settings: Whose proofs count.
    :return: The step opening a draft for finding #7.
    """
    return FindingDraftOpening(
        FindingRecheck(board, runner(outcome), [settings.owner], 7),
        DraftOpening(
            work,
            github,
            StackPlacement(github, github, github, github),
            "A title",
            "A body",
        ),
    )


def test_a_draft_for_an_accepted_proven_finding_closes_it_when_merged(
    work: WritePolicy, settings: WorkflowSettings
):
    board = labelled_board(proven(finding(7, FindingStage.ACCEPTED, Priority.HIGH)))
    with_proof_posted(board, 7, settings.owner)
    github = DescribedDraftsInMemory({})

    draft_for_finding(work, github, board, ProofOutcome.FAILS, settings).run()

    assert github.descriptions == {1: f"A body\n\n{ClosingKeyword.FIXES.reference(7)}"}


def test_a_draft_for_a_finding_the_person_has_not_accepted_is_refused(
    work: WritePolicy, settings: WorkflowSettings
):
    board = labelled_board(proven(finding(7, FindingStage.UNREVIEWED, Priority.HIGH)))
    with_proof_posted(board, 7, settings.owner)
    github = DescribedDraftsInMemory({})

    with pytest.raises(FindingNotAcceptedError):
        draft_for_finding(work, github, board, ProofOutcome.FAILS, settings).run()

    assert github.writes == []


def test_a_draft_for_an_unproven_finding_is_refused(
    work: WritePolicy, settings: WorkflowSettings
):
    board = labelled_board(finding(7, FindingStage.ACCEPTED, Priority.HIGH))
    github = DescribedDraftsInMemory({})

    with pytest.raises(MissingProofError):
        draft_for_finding(work, github, board, ProofOutcome.FAILS, settings).run()

    assert github.writes == []


def test_a_draft_for_a_finding_whose_test_now_passes_is_refused(
    work: WritePolicy, settings: WorkflowSettings
):
    board = labelled_board(proven(finding(7, FindingStage.ACCEPTED, Priority.HIGH)))
    with_proof_posted(board, 7, settings.owner)
    github = DescribedDraftsInMemory({})

    with pytest.raises(ProofNoLongerHoldsError):
        draft_for_finding(work, github, board, ProofOutcome.PASSES, settings).run()

    assert github.writes == []


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


def test_the_summary_counts_the_proven_among_the_accepted():
    board = IssuesInMemory(
        {
            1: proven(finding(1, FindingStage.ACCEPTED, Priority.HIGH)),
            2: finding(2, FindingStage.ACCEPTED, Priority.LOW),
        }
    )

    [line] = FindingsSummary(board).lines()

    assert line.text == (
        "github-workflow: findings: 0 unreviewed, 2 accepted (1 proven)"
    )


def test_a_repository_without_findings_says_nothing():
    assert FindingsSummary(IssuesInMemory()).lines() == []
