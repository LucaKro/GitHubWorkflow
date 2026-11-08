"""
Findings: what a session notices outside its work, filed as unreviewed GitHub issues
with a priority rather than acted on. Only the person accepts, shelves or rejects them;
a finding is proven by a test failing on the default branch, posted on its issue, and
only an accepted, proven one is worked on in a draft pull request.
"""

from __future__ import annotations

from abc import ABC
from collections.abc import Collection, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Self

from basstler_domain_model.class_property import classproperty
from basstler_domain_model.github.closing_lines import ClosingLines
from basstler_domain_model.github.issue_models import Issue
from basstler_domain_model.github.repository_client import (
    IssueBoard,
    PullRequestCloser,
    PullRequestReader,
    RepositoryLabels,
)
from basstler_domain_model.github.vocabulary import (
    ClosingKeyword,
    IssueState,
    IssueStateReason,
)
from basstler_domain_model.repository import Repository

from github_workflow.command_line import PriorityLevel
from github_workflow.exceptions import (
    AlreadyProvenError,
    BrokenTestError,
    FindingNotAcceptedError,
    FindingStillFailsError,
    FixNotMergedError,
    MissingProofError,
    NotAFindingError,
    NothingToEditError,
    ProofNoLongerHoldsError,
    UnprovenFindingCloseError,
)
from github_workflow.labels import DescribedLabel
from github_workflow.proofs import FindingTest, Proof, ProofOutcome, ProofRunner
from github_workflow.report_lines import (
    Emphasis,
    Highlight,
    NumberLink,
    ReportLine,
    Tone,
)
from github_workflow.report_section import ReportGroup, ReportSection
from github_workflow.work import (
    DraftOpening,
    PullRequestOpenedLabelling,
    PullRequestRetirement,
    SessionLog,
    WorkflowStep,
)

# %% the labels


class FindingLabel(DescribedLabel):
    """
    The base of the labels a finding carries.
    """

    @classmethod
    def from_issue(cls, issue: Issue) -> Self | None:
        """
        :param issue: An issue.
        :return: The first of these labels it carries, ``None`` when it carries none.
        """
        return next((label for label in cls if label in issue.labels), None)

    @classproperty
    def every_label(cls) -> list[FindingLabel]:
        """
        Every label of every kind a finding carries.
        """
        return [label for kind in cls.__subclasses__() for label in kind]


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

    @classproperty
    def open_stages(cls) -> list[FindingStage]:
        """
        The stages of a finding that is still open.
        """
        return [cls.UNREVIEWED, cls.ACCEPTED, cls.SHELVED]

    @classproperty
    def by_caution(cls) -> list[FindingStage]:
        """
        The stages, the most cautious first: a stage the person picked before the one a
        session files with, and of the person's, the one doing least.
        """
        return [cls.INCORRECT, cls.SHELVED, cls.ACCEPTED, cls.UNREVIEWED]

    @classmethod
    def from_issue(cls, issue: Issue) -> FindingStage | None:
        """
        Unlike :meth:`FindingLabel.from_issue`, of several stage labels the first in
        :attr:`by_caution` counts, so a stage picked on GitHub counts even while the
        label it replaces is still on.
        """
        return next((stage for stage in cls.by_caution if stage in issue.labels), None)


class Priority(FindingLabel):
    """
    How urgent a finding is, as the session that files it judges: the label of each
    :class:`PriorityLevel`, which it means.
    """

    CRITICAL = (
        f"priority: {PriorityLevel.CRITICAL}",
        PriorityLevel.CRITICAL.meaning,
        "b60205",
    )
    """
    The label of :attr:`PriorityLevel.CRITICAL`.
    """

    HIGH = (f"priority: {PriorityLevel.HIGH}", PriorityLevel.HIGH.meaning, "d93f0b")
    """
    The label of :attr:`PriorityLevel.HIGH`.
    """

    MEDIUM = (
        f"priority: {PriorityLevel.MEDIUM}",
        PriorityLevel.MEDIUM.meaning,
        "fbca04",
    )
    """
    The label of :attr:`PriorityLevel.MEDIUM`.
    """

    LOW = (f"priority: {PriorityLevel.LOW}", PriorityLevel.LOW.meaning, "c5def5")
    """
    The label of :attr:`PriorityLevel.LOW`.
    """

    @property
    def level(self) -> PriorityLevel:
        """:return: The priority's level alone, as the command line takes it."""
        return PriorityLevel[self._name_]

    @classmethod
    def at_level(cls, level: PriorityLevel) -> Priority:
        """
        :param level: A priority level.
        :return: Its label.
        """
        return cls[level._name_]

    @classmethod
    def most_urgent_first(cls, issues: Sequence[Issue]) -> list[Issue]:
        """
        :param issues: Findings.
        :return: Them, most urgent first, those without a priority last.
        """
        return sorted(
            issues, key=lambda issue: list(cls).index(cls.from_issue(issue) or cls.LOW)
        )

    @classmethod
    def named(cls, issue: Issue, repository: Repository) -> str:
        """
        :param issue: A finding.
        :param repository: The repository it is filed on.
        :return: Its number linked to its page, priority level and title, as one line
            names it.
        """
        priority = cls.from_issue(issue)
        level = priority.level if priority else "no priority"
        link = NumberLink(issue.number, repository.issue_url(issue.number))
        return f"{link.markdown()} [{level}] {issue.title}"

    @classmethod
    def emphases(cls, issue: Issue) -> tuple[Emphasis, ...]:
        """
        :param issue: A finding.
        :return: Its priority tag, as :meth:`named` writes it, in the priority's own
            style; nothing for a finding without a priority.
        """
        priority = cls.from_issue(issue)
        if priority is None:
            return ()
        return (Emphasis(f"[{priority.level}]", Highlight[priority._name_]),)


class ClosedBy(FindingLabel):
    """
    Who closed a finding or a pull request, when it was not the person, so they can
    list what sessions closed.
    """

    SESSION = (
        "closed by session",
        "Closed by a session on its own: a fixed finding, or a draft it replaced or "
        "discarded",
        "c2e0c6",
    )
    """
    Closed by a session.
    """


class Evidence(FindingLabel):
    """
    Whether a test failing on the default branch shows a finding; a finding carries none
    until a session tries to prove it.
    """

    PROVEN = (
        "finding: proven",
        "A test failing on the default branch is posted on the issue",
        "1d76db",
    )
    """
    A session posted the proof; only one the owner or the workflow's account posted
    counts.
    """

    UNPROVEN = (
        "finding: unproven",
        "No test failing on the default branch could be written",
        "bfd4f2",
    )
    """
    A session tried, and could write no test failing on the default branch.
    """


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
        Create every finding label the repository does not carry yet.
        """
        self.labels.create_missing_labels(FindingLabel.every_label)

    def relabel(self, issue: Issue, labels: Sequence[FindingLabel]) -> None:
        """
        Give an issue these labels, removing every other label of their kinds it
        carries.

        :param issue: The issue as it is labelled now.
        :param labels: At most one label of each kind.
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
        number = self.file([])
        return f"filed finding #{number} ({self.priority.level})"

    def file(self, evidence: Sequence[Evidence]) -> int:
        """
        :param evidence: The evidence it is filed with, if any.
        :return: The number of the issue filed.
        """
        self.create_missing_labels()
        return self.board.open_issue(
            self.title, self.body, [FindingStage.UNREVIEWED, self.priority, *evidence]
        )


@dataclass(frozen=True)
class ProvenFindingFiling(FindingFiling):
    """
    A finding filed as an unreviewed issue with its priority, proven by a test failing
    on the default branch; nothing is filed when the test does not fail there.
    """

    test: FindingTest
    """
    The test showing the finding.
    """

    runner: ProofRunner
    """
    Runs the test on the default branch.
    """

    def run(self) -> str:
        """
        :raises PassingTestError: If the test passes on the default branch.
        :raises BrokenTestError: If the test is broken.
        """
        proof = self.runner.attempt(self.test).proof()
        number = self.file([Evidence.PROVEN])
        self.board.add_comment(number, proof.comment())
        return f"filed finding #{number} ({self.priority.level}), proven on {proof.tip}"


@dataclass(frozen=True)
class OpenFindings:
    """
    The open findings on a board, each once, under the stage it counts as.
    """

    board: IssueBoard
    """
    Lists the issues.
    """

    def by_stage(self) -> dict[FindingStage, list[Issue]]:
        """
        :return: The open findings of each open stage, in the order of
            :attr:`FindingStage.open_stages`.
        """
        found = {
            issue.number: issue
            for stage in FindingStage.open_stages
            for issue in self.board.issues([stage], IssueState.OPEN)
        }
        grouped: dict[FindingStage, list[Issue]] = {
            stage: [] for stage in FindingStage.open_stages
        }
        for issue in found.values():
            stage = FindingStage.from_issue(issue)
            if stage in grouped:
                grouped[stage].append(issue)
        return grouped


@dataclass(frozen=True)
class FindingListing(WorkflowStep):
    """
    The open findings, unreviewed first and shelved last, most urgent first.
    """

    board: IssueBoard
    """
    Lists the issues.
    """

    repository: Repository
    """
    The repository the board is of.
    """

    def run(self) -> str:
        """
        :return: One finding per line; overrides :meth:`WorkflowStep.run`, which
            reports in one line.
        """
        lines = []
        for stage, issues in OpenFindings(self.board).by_stage().items():
            for issue in Priority.most_urgent_first(issues):
                evidence = Evidence.from_issue(issue)
                labels = f"{stage}, {evidence}" if evidence else stage
                lines.append(f"{Priority.named(issue, self.repository)} ({labels})")
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
        stage = [] if FindingStage.from_issue(issue) else [FindingStage.UNREVIEWED]
        self.relabel(issue, [self.priority, *stage])
        return f"prioritized #{self.number} as {self.priority.level}"


# %% changing one open finding


@dataclass(frozen=True)
class FindingChange(FindingLabelling, ABC):
    """
    A write to one open finding.
    """

    number: int
    """
    The finding.
    """

    def open_finding(self, stages: Sequence[FindingStage]) -> Issue:
        """
        :param stages: The stages the change applies to.
        :return: The finding, open in one of them.
        :raises NotAFindingError: If it is no open finding in one of them.
        """
        issue = self.board.issue(self.number)
        if (
            issue.state is not IssueState.OPEN
            or FindingStage.from_issue(issue) not in stages
        ):
            raise NotAFindingError(self.number)
        return issue


# %% the person's decisions


@dataclass(frozen=True)
class FindingAcceptance(FindingChange):
    """
    An unreviewed or shelved finding accepted, on the person's word.
    """

    def run(self) -> str:
        issue = self.open_finding([FindingStage.UNREVIEWED, FindingStage.SHELVED])
        self.relabel(issue, [FindingStage.ACCEPTED])
        return f"accepted finding #{self.number}"


@dataclass(frozen=True)
class FindingShelving(FindingChange):
    """
    An unreviewed or accepted finding set aside, left open, on the person's word.
    """

    def run(self) -> str:
        issue = self.open_finding([FindingStage.UNREVIEWED, FindingStage.ACCEPTED])
        self.relabel(issue, [FindingStage.SHELVED])
        return f"shelved finding #{self.number}"


@dataclass(frozen=True)
class FindingRejection(FindingChange):
    """
    An open finding rejected on the person's word: marked incorrect, the reason
    commented, the issue closed as not planned, so later sessions do not raise it again.
    """

    reason: str
    """
    Why it is rejected.
    """

    def run(self) -> str:
        issue = self.open_finding(FindingStage.open_stages)
        self.relabel(issue, [FindingStage.INCORRECT])
        self.board.add_comment(self.number, f"Rejected: {self.reason}")
        self.board.close_issue(self.number, IssueStateReason.NOT_PLANNED)
        return f"rejected finding #{self.number}"


# %% closing a fixed finding


@dataclass(frozen=True)
class FindingClosing(FindingChange):
    """
    An open, accepted, proven finding closed as completed, without asking, once the
    code shows it fixed: the pull request named is merged into the default branch, and
    the finding's proof test now passes there. Labelled :attr:`ClosedBy.SESSION`, with
    a comment naming the pull request, and entered in the session log.

    :raises FindingNotAcceptedError: If it is no open, accepted finding.
    :raises UnprovenFindingCloseError: If it carries no proof a trusted author posted.
    :raises FixNotMergedError: If the pull request is not merged into the default
        branch.
    :raises FindingStillFailsError: If its proof test still fails there.
    :raises BrokenTestError: If its proof test did not run.
    """

    pull_requests: PullRequestReader
    """
    Reads the pull request named as the fix.
    """

    runner: ProofRunner
    """
    Runs the proof test on the default branch.
    """

    authors: Collection[str]
    """
    The logins whose proofs count.
    """

    default_branch: str
    """
    The branch the fix has to be merged into.
    """

    fixed_by: int
    """
    The pull request that fixed it.
    """

    log: SessionLog
    """
    Where the close is entered.
    """

    def run(self) -> str:
        issue = self.board.issue(self.number)
        accepted = FindingStage.from_issue(issue) is FindingStage.ACCEPTED
        if issue.state is not IssueState.OPEN or not accepted:
            raise FindingNotAcceptedError(self.number)
        proof = Proof.posted_in(self.board.comments(self.number), self.authors)
        if Evidence.from_issue(issue) is not Evidence.PROVEN or proof is None:
            raise UnprovenFindingCloseError(self.number)
        fix = self.pull_requests.pull_request(self.fixed_by)
        if not fix.merged or fix.base != self.default_branch:
            raise FixNotMergedError(self.fixed_by, self.default_branch)
        attempt = self.runner.attempt(proof.test)
        if attempt.outcome is ProofOutcome.BROKEN:
            raise BrokenTestError(str(proof.test.path), attempt.message)
        if attempt.outcome is ProofOutcome.FAILS:
            raise FindingStillFailsError(self.number, attempt.tip, attempt.message)
        self.create_missing_labels()
        self.board.add_labels(self.number, [ClosedBy.SESSION])
        self.board.add_comment(
            self.number,
            f"Fixed by #{self.fixed_by}: its proof test passes on {attempt.tip}. "
            f"Closed by a session on its own.",
        )
        self.board.close_issue(self.number, IssueStateReason.COMPLETED)
        self.log.enter(
            f"closed finding #{self.number} as fixed by #{self.fixed_by}, its proof test "
            f"passing on {attempt.tip}"
        )
        return (
            f"closed finding #{self.number}, fixed by #{self.fixed_by}; tell the person "
            f"you closed it"
        )


# %% closing a session's own pull requests


@dataclass(frozen=True)
class SessionPullRequestClosing(PullRequestRetirement):
    """
    A pull request closed by a session, labelled :attr:`ClosedBy.SESSION`, commented
    with why and entered in the session log, so the person can list it and reopen it;
    the issues it closes lose :attr:`IssueLabel.PULL_REQUEST_OPENED`.
    """

    board: IssueBoard
    """
    Labels and comments on it, a pull request being an issue to GitHub too.
    """

    labels: RepositoryLabels
    """
    Creates the label when the repository lacks it.
    """

    closer: PullRequestCloser
    """
    Closes it.
    """

    log: SessionLog
    """
    Where the close is entered.
    """

    pull_requests: PullRequestReader
    """
    Reads its description.
    """

    issue_labels: PullRequestOpenedLabelling
    """
    Takes the label saying a pull request is open off the issues it closes.
    """

    def retire(self, number: int, reason: str) -> None:
        self.labels.create_missing_labels([ClosedBy.SESSION])
        self.board.add_labels(number, [ClosedBy.SESSION])
        self.board.add_comment(number, f"{reason} Closed by a session on its own.")
        self.closer.close_pull_request(number)
        self.issue_labels.unlabel(self.pull_requests.pull_request(number).body or "")
        self.log.enter(f"closed pull request #{number}: {reason}")


# %% commenting and editing


@dataclass(frozen=True)
class FindingComment(FindingChange):
    """
    A comment on a finding, open or closed, such as a correction made after it was
    closed.
    """

    body: str
    """
    The comment.
    """

    def run(self) -> str:
        """
        :raises NotAFindingError: If the issue is no finding.
        """
        if FindingStage.from_issue(self.board.issue(self.number)) is None:
            raise NotAFindingError(self.number)
        url = self.board.add_comment(self.number, self.body)
        return f"commented on finding #{self.number}: {url}"


@dataclass(frozen=True)
class FindingEdit(FindingChange):
    """
    An open finding's title, text or both rewritten, the rest left as it is.

    :raises NothingToEditError: If neither is given.
    """

    title: str | None
    """
    The new title, ``None`` to keep the old one.
    """

    body: str | None
    """
    The new text, ``None`` to keep the old one.
    """

    def run(self) -> str:
        if self.title is None and self.body is None:
            raise NothingToEditError(self.number)
        self.open_finding(FindingStage.open_stages)
        if self.title is not None:
            self.board.set_issue_title(self.number, self.title)
        if self.body is not None:
            self.board.set_issue_description(self.number, self.body)
        return f"edited finding #{self.number}"


# %% proving


@dataclass(frozen=True)
class FindingProving(FindingChange):
    """
    An open finding proven by a test failing on the branch its runner runs it on, the
    default branch unless an open pull request's or another branch is named: the proof,
    which records that branch and commit, posted on its issue, which is labelled proven.
    Nothing is written when the test does not fail there.
    """

    test: FindingTest
    """
    The test showing the finding.
    """

    runner: ProofRunner
    """
    Runs the test on its branch.
    """

    def run(self) -> str:
        """
        :raises NotAFindingError: If it is no open finding.
        :raises PassingTestError: If the test passes on the branch.
        :raises BrokenTestError: If the test is broken.
        """
        issue = self.open_finding(FindingStage.open_stages)
        proof = self.runner.attempt(self.test).proof()
        self.board.add_comment(self.number, proof.comment())
        self.relabel(issue, [Evidence.PROVEN])
        return f"proved finding #{self.number} on {proof.tip}"


@dataclass(frozen=True)
class FindingUnproving(FindingChange):
    """
    An open finding no test failing on the default branch could be written for: the
    reason commented, the issue labelled unproven.
    """

    reason: str
    """
    Why no such test could be written.
    """

    def run(self) -> str:
        """
        :raises NotAFindingError: If it is no open finding.
        :raises AlreadyProvenError: If it is proven.
        """
        issue = self.open_finding(FindingStage.open_stages)
        if Evidence.from_issue(issue) is Evidence.PROVEN:
            raise AlreadyProvenError(self.number)
        self.board.add_comment(self.number, f"Unproven: {self.reason}")
        self.relabel(issue, [Evidence.UNPROVEN])
        return f"marked finding #{self.number} unproven"


@dataclass(frozen=True)
class FindingRecheck(WorkflowStep):
    """
    The test proving a finding run again on its runner's branch as GitHub has it now,
    the default branch unless an open pull request's or another branch is named,
    writing nothing.
    """

    board: IssueBoard
    """
    Reads the finding and its comments.
    """

    runner: ProofRunner
    """
    Runs the test on its branch.
    """

    authors: Collection[str]
    """
    The logins whose proofs count.
    """

    number: int
    """
    The finding.
    """

    def run(self) -> str:
        """
        :raises MissingProofError: If it is not proven by a test a trusted author
            posted.
        :raises ProofNoLongerHoldsError: If the test passes.
        :raises BrokenTestError: If the test did not run, or fails only because it is
            broken.
        """
        issue = self.board.issue(self.number)
        proof = Proof.posted_in(self.board.comments(self.number), self.authors)
        if Evidence.from_issue(issue) is not Evidence.PROVEN or proof is None:
            raise MissingProofError(self.number)
        attempt = self.runner.attempt(proof.test)
        if attempt.outcome is ProofOutcome.BROKEN:
            raise BrokenTestError(str(proof.test.path), attempt.message)
        if attempt.outcome is ProofOutcome.PASSES:
            raise ProofNoLongerHoldsError(self.number, attempt.tip)
        return f"#{self.number} still fails on {attempt.tip}: {attempt.message}"


# %% working on a finding


@dataclass(frozen=True)
class FindingDraftOpening(WorkflowStep):
    """
    A draft pull request working on an open, accepted finding whose proof still holds,
    closing the finding when it is merged.
    """

    recheck: FindingRecheck
    """
    Runs the finding's proof again first.
    """

    draft: DraftOpening
    """
    Opens the draft.
    """

    def run(self) -> str:
        """
        :raises FindingNotAcceptedError: If it is no open, accepted finding.
        :raises MissingProofError: If it is not proven.
        :raises ProofNoLongerHoldsError: If its test no longer fails.
        """
        number = self.recheck.number
        issue = self.recheck.board.issue(number)
        if (
            issue.state is not IssueState.OPEN
            or FindingStage.from_issue(issue) is not FindingStage.ACCEPTED
        ):
            raise FindingNotAcceptedError(number)
        self.recheck.run()
        fixes = ClosingKeyword.FIXES.reference(number)
        body = (
            self.draft.body
            if fixes in ClosingLines(self.draft.body).lines()
            else f"{self.draft.body}\n\n{fixes}"
        )
        return f"{replace(self.draft, body=body).run()}, for finding #{number}"


# %% the section


class FindingGroup(StrEnum):
    """
    The groups the session start lists open findings in, in the order shown, each
    member's value its heading; a shelved finding is in none.
    """

    UNREVIEWED = "findings waiting on your review"
    """
    Filed, and not looked at by the person yet.
    """

    PROVEN = "accepted findings, proven"
    """
    Accepted, with a test failing on the default branch: ready to work on.
    """

    TO_PROVE = "accepted findings, not proven yet"
    """
    Accepted, with no attempt at a failing test yet.
    """

    UNPROVABLE = "accepted findings, marked unproven"
    """
    Accepted, and no test failing on the default branch could be written.
    """

    @classmethod
    def from_finding(cls, stage: FindingStage, issue: Issue) -> FindingGroup | None:
        """
        :param stage: The stage the finding counts as.
        :param issue: The finding.
        :return: The group it is listed in, ``None`` for a shelved one.
        """
        if stage is FindingStage.UNREVIEWED:
            return cls.UNREVIEWED
        if stage is not FindingStage.ACCEPTED:
            return None
        match Evidence.from_issue(issue):
            case Evidence.PROVEN:
                return cls.PROVEN
            case Evidence.UNPROVEN:
                return cls.UNPROVABLE
            case None:
                return cls.TO_PROVE


@dataclass(frozen=True)
class FindingsSummary(ReportSection):
    """
    The open findings the person or a session acts on, each named under its
    :class:`FindingGroup`, most urgent first; shelved findings are left out.
    """

    board: IssueBoard
    """
    Lists the issues.
    """

    repository: Repository
    """
    The repository the board is of.
    """

    def lines(self) -> list[ReportLine]:
        grouped: dict[FindingGroup, list[Issue]] = {group: [] for group in FindingGroup}
        for stage, issues in OpenFindings(self.board).by_stage().items():
            for issue in issues:
                group = FindingGroup.from_finding(stage, issue)
                if group is not None:
                    grouped[group].append(issue)
        lines = []
        for group, issues in grouped.items():
            tone = Tone.ACTION if group is FindingGroup.UNREVIEWED else Tone.NEWS
            items = [
                ReportLine(
                    Priority.named(issue, self.repository),
                    tone,
                    emphases=Priority.emphases(issue),
                )
                for issue in Priority.most_urgent_first(issues)
            ]
            lines += ReportGroup(group, items).lines()
        return lines
