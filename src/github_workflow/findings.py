"""
Findings: what a session notices outside the work it is doing, kept as GitHub issues
rather than acted on.

Filed or prioritized as unreviewed with a priority; only the person accepts, shelves or
rejects them. A finding is proven by a test failing on the default branch, posted on its
issue; only an accepted, proven finding is worked on in a draft pull request.
"""

from __future__ import annotations

from abc import ABC
from collections import Counter
from collections.abc import Collection, Sequence
from dataclasses import dataclass, replace
from enum import ReprEnum
from typing import Self

from basstler_domain_model.class_property import classproperty
from basstler_domain_model.github.issue_models import Issue
from basstler_domain_model.github.labels import GitHubLabel
from basstler_domain_model.github.repository_client import (
    IssueBoard,
    RepositoryLabels,
)
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
    ProofNoLongerHoldsError,
)
from github_workflow.hooks import ReportLine, Tone
from github_workflow.proofs import FindingTest, Proof, ProofOutcome, ProofRunner
from github_workflow.report_section import ReportSection
from github_workflow.work import DraftOpening, WorkflowStep

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
    def of(cls, issue: Issue) -> FindingStage | None:
        """
        Unlike :meth:`FindingLabel.of`, of several stage labels the first in
        :attr:`by_caution` counts, so a stage picked on GitHub counts even while the
        label it replaces is still on.
        """
        return next((stage for stage in cls.by_caution if stage in issue.labels), None)


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
    A test failing on the default branch is posted on the issue.
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
        present = self.labels.labels()
        for label in FindingLabel.every_label:
            if label not in present:
                self.labels.create_label(label)

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
            stage = FindingStage.of(issue)
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

    def run(self) -> str:
        """
        :return: One finding per line; overrides :meth:`WorkflowStep.run`, which
            reports in one line.
        """
        lines = []
        for stage, issues in OpenFindings(self.board).by_stage().items():
            for issue in sorted(
                issues,
                key=lambda issue: list(Priority).index(
                    Priority.of(issue) or Priority.LOW
                ),
            ):
                priority = Priority.of(issue)
                level = priority.level if priority else "no priority"
                evidence = Evidence.of(issue)
                labels = f"{stage}, {evidence}" if evidence else stage
                lines.append(f"#{issue.number} [{level}] {issue.title} ({labels})")
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
        if issue.state is not IssueState.OPEN or FindingStage.of(issue) not in stages:
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


# %% commenting and editing


@dataclass(frozen=True)
class FindingComment(FindingChange):
    """
    A comment on an open finding.
    """

    body: str
    """
    The comment.
    """

    def run(self) -> str:
        self.open_finding(FindingStage.open_stages)
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
    An open finding proven by a test failing on the default branch: the proof posted on
    its issue, which is labelled proven. Nothing is written when the test does not fail
    there.
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
        :raises NotAFindingError: If it is no open finding.
        :raises PassingTestError: If the test passes on the default branch.
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
        if Evidence.of(issue) is Evidence.PROVEN:
            raise AlreadyProvenError(self.number)
        self.board.add_comment(self.number, f"Unproven: {self.reason}")
        self.relabel(issue, [Evidence.UNPROVEN])
        return f"marked finding #{self.number} unproven"


@dataclass(frozen=True)
class FindingRecheck(WorkflowStep):
    """
    The test proving a finding run again on the default branch as GitHub has it now,
    writing nothing.
    """

    board: IssueBoard
    """
    Reads the finding and its comments.
    """

    runner: ProofRunner
    """
    Runs the test on the default branch.
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
        if Evidence.of(issue) is not Evidence.PROVEN or proof is None:
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
            or FindingStage.of(issue) is not FindingStage.ACCEPTED
        ):
            raise FindingNotAcceptedError(number)
        self.recheck.run()
        body = f"{self.draft.body}\n\n{ClosingKeyword.FIXES.reference(number)}"
        return f"{replace(self.draft, body=body).run()}, for finding #{number}"


# %% the section


@dataclass(frozen=True)
class FindingsSummary(ReportSection):
    """
    How many findings wait for the person, by priority, how many are accepted and how
    many of those proven, and how many are shelved.
    """

    board: IssueBoard
    """
    Lists the issues.
    """

    def lines(self) -> list[ReportLine]:
        by_stage = OpenFindings(self.board).by_stage()
        unreviewed = by_stage[FindingStage.UNREVIEWED]
        accepted = by_stage[FindingStage.ACCEPTED]
        shelved = by_stage[FindingStage.SHELVED]
        if not unreviewed and not accepted and not shelved:
            return []
        counted = Counter(Priority.of(issue) for issue in unreviewed)
        by_priority = ", ".join(
            f"{counted[priority]} {priority.level}"
            for priority in Priority
            if counted[priority]
        )
        detail = f" ({by_priority})" if by_priority else ""
        proven = sum(Evidence.of(issue) is Evidence.PROVEN for issue in accepted)
        ready = f" ({proven} proven)" if proven else ""
        set_aside = f", {len(shelved)} shelved" if shelved else ""
        return [
            ReportLine(
                f"github-workflow: findings: {len(unreviewed)} unreviewed{detail}, "
                f"{len(accepted)} accepted{ready}{set_aside}",
                Tone.ACTION if unreviewed else Tone.NEWS,
            )
        ]
