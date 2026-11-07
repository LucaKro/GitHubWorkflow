"""
Tests for :mod:`github_workflow.findings`: findings are filed or prioritized as
unreviewed with a priority, listed most urgent first, moved on only by the person's
accept, shelve or reject, proven by a test failing on the default branch, and worked on
in a draft only once accepted and proven.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest

from basstler_domain_model.github.issue_models import Issue, IssueComment
from basstler_domain_model.github.repository_client import (
    PullRequestCloser,
    PullRequestReader,
)
from basstler_domain_model.github.rest_models import RestPullRequest
from basstler_domain_model.repository import Repository
from basstler_domain_model.github.vocabulary import (
    ClosingKeyword,
    IssueState,
    IssueStateReason,
    PullRequestState,
)

from github_workflow.exceptions import (
    AlreadyProvenError,
    BrokenTestError,
    FindingNotAcceptedError,
    FindingStillFailsError,
    FixNotMergedError,
    MissingProofError,
    NotAFindingError,
    NothingToEditError,
    PassingTestError,
    ProofNoLongerHoldsError,
    UnprovenFindingCloseError,
)
from github_workflow.findings import (
    ClosedBy,
    Evidence,
    FindingAcceptance,
    FindingClosing,
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
    FindingGroup,
    FindingsSummary,
    FindingStage,
    FindingUnproving,
    Priority,
    ProvenFindingFiling,
    SessionPullRequestClosing,
)
from github_workflow.hooks import ReportLine, Tone
from github_workflow.policy import WritePolicy
from github_workflow.report_section import ReportGroup
from github_workflow.proofs import BranchTip, FindingTest, ProofAttempt, ProofOutcome
from github_workflow.settings import WorkflowSettings
from github_workflow.stacks import StackPlacement
from github_workflow.work import DraftOpening, IssueLabel, PullRequestOpenedLabelling

from .issues_in_memory import (
    IssuesInMemory,
    PresetOutcomeRunner,
    finding,
    labelled_board,
)
from .pull_requests import pull_request
from .stacked_pull_requests import DraftsAndStacksInMemory
from .test_work import EntriesInMemory, work

FINDINGS_REPOSITORY = Repository("LucaKro", "project")
"""
The repository the findings here are filed on.
"""

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


def accepted_on_github(issue: Issue) -> Issue:
    """:param issue: An unreviewed finding.
    :return: It, as the person leaves it by picking the accepted label on GitHub, the
        unreviewed label still on it."""
    return Issue(
        issue.number,
        issue.title,
        (*issue.labels, FindingStage.ACCEPTED),
        issue.state,
    )


def test_a_stage_the_person_picked_outranks_unreviewed():
    issue = accepted_on_github(finding(1, FindingStage.UNREVIEWED, Priority.HIGH))

    assert FindingStage.of(issue) is FindingStage.ACCEPTED


@pytest.mark.parametrize(
    "picked, counted",
    [
        ((FindingStage.ACCEPTED, FindingStage.SHELVED), FindingStage.SHELVED),
        ((FindingStage.ACCEPTED, FindingStage.INCORRECT), FindingStage.INCORRECT),
        ((FindingStage.SHELVED, FindingStage.INCORRECT), FindingStage.INCORRECT),
    ],
    ids=["shelved over accepted", "incorrect over accepted", "incorrect over shelved"],
)
def test_of_two_stages_the_person_picked_the_more_cautious_counts(
    picked: tuple[FindingStage, FindingStage], counted: FindingStage
):
    issue = Issue(1, "Finding 1", (*picked, Priority.HIGH), IssueState.OPEN)

    assert FindingStage.of(issue) is counted


def test_a_finding_accepted_on_github_is_listed_once_as_accepted():
    unreviewed = finding(1, FindingStage.UNREVIEWED, Priority.HIGH)
    board = IssuesInMemory({1: accepted_on_github(unreviewed)})

    listed = FindingListing(board, FINDINGS_REPOSITORY).run().splitlines()

    assert listed == [
        f"{Priority.named(unreviewed, FINDINGS_REPOSITORY)} ({FindingStage.ACCEPTED})"
    ]


def test_a_finding_accepted_on_github_is_summed_up_once_as_accepted():
    accepted = accepted_on_github(finding(1, FindingStage.UNREVIEWED, Priority.HIGH))
    board = IssuesInMemory({1: accepted})

    lines = FindingsSummary(board, FINDINGS_REPOSITORY).lines()

    assert lines == grouped(FindingGroup.TO_PROVE, [accepted], Tone.NEWS)


def test_findings_are_listed_unreviewed_first_and_most_urgent_first():
    board = IssuesInMemory(
        {
            1: finding(1, FindingStage.ACCEPTED, Priority.CRITICAL),
            2: finding(2, FindingStage.UNREVIEWED, Priority.LOW),
            3: finding(3, FindingStage.UNREVIEWED, Priority.CRITICAL),
        }
    )

    listed = FindingListing(board, FINDINGS_REPOSITORY).run().splitlines()

    assert [line.split()[0] for line in listed] == ["#3", "#2", "#1"]


def test_shelved_findings_are_listed_after_the_accepted():
    board = IssuesInMemory(
        {
            1: finding(1, FindingStage.SHELVED, Priority.CRITICAL),
            2: finding(2, FindingStage.ACCEPTED, Priority.LOW),
        }
    )

    listed = FindingListing(board, FINDINGS_REPOSITORY).run().splitlines()

    assert [line.split()[0] for line in listed] == ["#2", "#1"]


def test_a_listed_finding_shows_its_evidence():
    board = IssuesInMemory({1: proven(finding(1, FindingStage.ACCEPTED, Priority.LOW))})

    listed = FindingListing(board, FINDINGS_REPOSITORY).run()

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


# %% closing a fixed finding


@dataclass(frozen=True)
class FixesInMemory(PullRequestReader):
    """
    Answers pull request 157, merged into the default branch or not.
    """

    merged: bool = True
    """
    Whether it is merged.
    """

    base: str = "main"
    """
    The branch it targets.
    """

    def pull_request(self, number: int) -> RestPullRequest:
        state = PullRequestState.CLOSED if self.merged else PullRequestState.OPEN
        opened = pull_request(number, "fix", state=state, base=self.base)
        return replace(opened, merged=self.merged)

    def open_pull_requests(self) -> list[RestPullRequest]:
        raise NotImplementedError


def closing(
    board: IssuesInMemory,
    settings: WorkflowSettings,
    outcome: ProofOutcome = ProofOutcome.PASSES,
    fixes: FixesInMemory = FixesInMemory(),
) -> FindingClosing:
    """
    :param board: The findings.
    :param settings: The workflow's settings.
    :param outcome: How the proof test fares on the default branch now.
    :param fixes: The pull request named as the fix.
    :return: The closing of finding 1 as fixed by pull request 157.
    """
    return FindingClosing(
        board,
        board,
        1,
        fixes,
        runner(outcome),
        [settings.owner],
        "main",
        157,
        EntriesInMemory(),
    )


def proven_accepted(settings: WorkflowSettings) -> IssuesInMemory:
    """
    :param settings: The workflow's settings.
    :return: A board with finding 1 accepted, proven, and its proof posted.
    """
    board = labelled_board(proven(finding(1, FindingStage.ACCEPTED, Priority.HIGH)))
    with_proof_posted(board, 1, settings.owner)
    return board


def test_a_fixed_finding_is_closed_as_completed_and_marked_as_a_session_s(
    settings: WorkflowSettings,
):
    board = proven_accepted(settings)

    closing(board, settings).run()

    assert [write.split()[0] for write in board.writes] == [
        "add_labels",
        "add_comment",
        "close_issue",
    ]
    assert board.writes[0] == f"add_labels 1 {[ClosedBy.SESSION]}"
    assert "#157" in board.writes[1]
    assert board.writes[2] == f"close_issue 1 {IssueStateReason.COMPLETED}"


def test_a_fixed_finding_s_close_is_entered_in_the_session_log(
    settings: WorkflowSettings,
):
    step = closing(proven_accepted(settings), settings)

    step.run()

    [entry] = step.log.entries
    assert f"finding #{step.number}" in entry
    assert f"#{step.fixed_by}" in entry


@pytest.mark.parametrize(
    "fixes",
    [FixesInMemory(merged=False), FixesInMemory(base="another-branch")],
    ids=["not merged", "merged elsewhere"],
)
def test_a_fix_not_merged_into_the_default_branch_closes_nothing(
    settings: WorkflowSettings, fixes: FixesInMemory
):
    board = proven_accepted(settings)

    with pytest.raises(FixNotMergedError):
        closing(board, settings, fixes=fixes).run()

    assert board.writes == []


@pytest.mark.parametrize(
    "outcome, error",
    [
        (ProofOutcome.FAILS, FindingStillFailsError),
        (ProofOutcome.BROKEN, BrokenTestError),
    ],
    ids=["still fails", "broken"],
)
def test_a_finding_whose_proof_does_not_pass_stays_open(
    settings: WorkflowSettings, outcome: ProofOutcome, error: type[Exception]
):
    board = proven_accepted(settings)

    with pytest.raises(error):
        closing(board, settings, outcome).run()

    assert board.writes == []


def test_an_unproven_finding_is_left_to_the_person(settings: WorkflowSettings):
    board = labelled_board(finding(1, FindingStage.ACCEPTED, Priority.HIGH))

    with pytest.raises(UnprovenFindingCloseError):
        closing(board, settings).run()

    assert board.writes == []


@pytest.mark.parametrize("stage", [FindingStage.UNREVIEWED, FindingStage.SHELVED])
def test_a_finding_the_person_has_not_accepted_is_not_closed(
    settings: WorkflowSettings, stage: FindingStage
):
    board = labelled_board(proven(finding(1, stage, Priority.HIGH)))
    with_proof_posted(board, 1, settings.owner)

    with pytest.raises(FindingNotAcceptedError):
        closing(board, settings).run()

    assert board.writes == []


# %% closing a session's own pull requests


@dataclass(frozen=True)
class ClosedInMemory(PullRequestCloser):
    """
    Records every pull request closed.
    """

    closed: list[int] = field(default_factory=list)
    """
    The pull requests closed, in order.
    """

    def close_pull_request(self, number: int) -> None:
        self.closed.append(number)


@dataclass(frozen=True)
class DescribedPullRequests(PullRequestReader):
    """
    Pull requests, each with the description given.
    """

    descriptions: dict[int, str]
    """
    Each pull request's description, by number.
    """

    def open_pull_requests(self) -> list[RestPullRequest]:
        return [self.pull_request(number) for number in self.descriptions]

    def pull_request(self, number: int) -> RestPullRequest:
        return replace(
            pull_request(number, f"branch-{number}"), body=self.descriptions[number]
        )


def session_closing(
    board: IssuesInMemory,
    closer: ClosedInMemory,
    log: EntriesInMemory,
    description: str = "A body",
) -> SessionPullRequestClosing:
    """
    :param board: The issues and labels.
    :param closer: Closes the pull request.
    :param log: The session log.
    :param description: The description of pull request #3.
    :return: Closes pull request #3 as a session's.
    """
    return SessionPullRequestClosing(
        board,
        board,
        closer,
        log,
        DescribedPullRequests({3: description}),
        PullRequestOpenedLabelling(board, board),
    )


@pytest.mark.parametrize("labelled", [True, False], ids=["label there", "label made"])
def test_a_session_s_pull_request_is_closed_marked_and_explained(labelled: bool):
    board = labelled_board() if labelled else IssuesInMemory({})
    closer = ClosedInMemory()

    session_closing(board, closer, EntriesInMemory()).retire(3, "Replaced by #5.")

    made = [] if labelled else [f"create_label {ClosedBy.SESSION}"]
    assert board.writes == [
        *made,
        f"add_labels 3 {[ClosedBy.SESSION]}",
        "add_comment 3 Replaced by #5. Closed by a session on its own.",
    ]
    assert closer.closed == [3]


def test_a_session_s_pull_request_close_is_entered_in_the_session_log():
    board = labelled_board()
    log = EntriesInMemory()

    session_closing(board, ClosedInMemory(), log).retire(3, "Replaced by #5.")

    [entry] = log.entries
    assert "#3" in entry
    assert "Replaced by #5." in entry


def test_the_issues_a_closed_pull_request_closes_lose_the_open_pull_request_label():
    fixed = finding(7, FindingStage.ACCEPTED, Priority.HIGH)
    board = IssuesInMemory(
        {7: replace(fixed, labels=(*fixed.labels, IssueLabel.PULL_REQUEST_OPENED))}
    )

    session_closing(
        board,
        ClosedInMemory(),
        EntriesInMemory(),
        f"A body\n\n{ClosingKeyword.FIXES.reference(7)}",
    ).retire(3, "Discarded.")

    assert IssueLabel.PULL_REQUEST_OPENED not in board.issue(7).labels


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


def test_a_closed_finding_is_not_edited():
    board = IssuesInMemory(
        {1: Issue(1, "Finding 1", (FindingStage.INCORRECT,), IssueState.CLOSED)}
    )

    with pytest.raises(NotAFindingError):
        FindingEdit(board, board, 1, "A title", None).run()

    assert board.writes == []


def test_a_closed_finding_takes_a_correction():
    board = IssuesInMemory(
        {1: Issue(1, "Finding 1", (FindingStage.ACCEPTED,), IssueState.CLOSED)}
    )

    FindingComment(board, board, 1, "A correction").run()

    assert board.writes == ["add_comment 1 A correction"]


def test_an_issue_that_is_no_finding_is_not_commented_on():
    board = IssuesInMemory({1: Issue(1, "An issue", ("bug",), IssueState.OPEN)})

    with pytest.raises(NotAFindingError):
        FindingComment(board, board, 1, "More").run()

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


def test_a_proof_whose_test_no_longer_fails_is_reported(settings: WorkflowSettings):
    board = labelled_board(proven(finding(1, FindingStage.ACCEPTED, Priority.HIGH)))
    with_proof_posted(board, 1, settings.owner)

    with pytest.raises(ProofNoLongerHoldsError):
        FindingRecheck(board, runner(ProofOutcome.PASSES), [settings.owner], 1).run()


def test_a_recheck_whose_test_never_ran_reports_it_broken(settings: WorkflowSettings):
    board = labelled_board(proven(finding(1, FindingStage.ACCEPTED, Priority.HIGH)))
    with_proof_posted(board, 1, settings.owner)

    with pytest.raises(BrokenTestError):
        FindingRecheck(board, runner(ProofOutcome.BROKEN), [settings.owner], 1).run()


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
            PullRequestOpenedLabelling(board, board),
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


def test_a_description_closing_the_finding_already_keeps_one_closing_line(
    work: WritePolicy, settings: WorkflowSettings
):
    board = labelled_board(proven(finding(7, FindingStage.ACCEPTED, Priority.HIGH)))
    with_proof_posted(board, 7, settings.owner)
    github = DescribedDraftsInMemory({})
    body = f"A body\n\n{ClosingKeyword.FIXES.reference(7)}"
    opening = draft_for_finding(work, github, board, ProofOutcome.FAILS, settings)

    replace(opening, draft=replace(opening.draft, body=body)).run()

    assert github.descriptions == {1: body}


def test_the_finding_a_draft_closes_is_labelled_as_having_a_pull_request(
    work: WritePolicy, settings: WorkflowSettings
):
    board = labelled_board(proven(finding(7, FindingStage.ACCEPTED, Priority.HIGH)))
    with_proof_posted(board, 7, settings.owner)

    draft_for_finding(
        work, DescribedDraftsInMemory({}), board, ProofOutcome.FAILS, settings
    ).run()

    assert IssueLabel.PULL_REQUEST_OPENED in board.issue(7).labels


def test_a_draft_for_a_finding_accepted_on_github_is_opened(
    work: WritePolicy, settings: WorkflowSettings
):
    """
    Picking the accepted label on GitHub leaves the unreviewed one on, without the label
    workflow to remove it.
    """
    board = labelled_board(
        proven(accepted_on_github(finding(7, FindingStage.UNREVIEWED, Priority.HIGH)))
    )
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


def unproven(issue: Issue) -> Issue:
    """:param issue: A finding.
    :return: It, labelled as no failing test could be written for it."""
    return Issue(
        issue.number, issue.title, (*issue.labels, Evidence.UNPROVEN), issue.state
    )


def grouped(group: FindingGroup, issues: list[Issue], tone: Tone) -> list[ReportLine]:
    """
    :param group: A group of findings.
    :param issues: The findings in it, in the order listed.
    :param tone: How they stand out.
    :return: The group's lines.
    """
    items = [
        ReportLine(Priority.named(issue, FINDINGS_REPOSITORY), tone) for issue in issues
    ]
    return ReportGroup(group, items).lines()


def test_the_summary_names_each_finding_in_its_group_most_urgent_first():
    issues = {
        1: finding(1, FindingStage.UNREVIEWED, Priority.LOW),
        2: finding(2, FindingStage.UNREVIEWED, Priority.CRITICAL),
        3: proven(finding(3, FindingStage.ACCEPTED, Priority.HIGH)),
        4: finding(4, FindingStage.ACCEPTED, Priority.MEDIUM),
        5: unproven(finding(5, FindingStage.ACCEPTED, Priority.LOW)),
    }

    lines = FindingsSummary(IssuesInMemory(issues), FINDINGS_REPOSITORY).lines()

    assert lines == [
        *grouped(FindingGroup.UNREVIEWED, [issues[2], issues[1]], Tone.ACTION),
        *grouped(FindingGroup.PROVEN, [issues[3]], Tone.NEWS),
        *grouped(FindingGroup.TO_PROVE, [issues[4]], Tone.NEWS),
        *grouped(FindingGroup.UNPROVABLE, [issues[5]], Tone.NEWS),
    ]


def test_the_summary_leaves_shelved_findings_out():
    board = IssuesInMemory({1: finding(1, FindingStage.SHELVED, Priority.HIGH)})

    assert FindingsSummary(board, FINDINGS_REPOSITORY).lines() == []


def test_a_repository_without_findings_says_nothing():
    assert FindingsSummary(IssuesInMemory(), FINDINGS_REPOSITORY).lines() == []
