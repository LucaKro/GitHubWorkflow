"""
A repository's issues and pull requests, their comments and labels in memory, for the
tests of what the workflow writes to them, and a stand-in for running a finding's test.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace

from domain_model.github.issue_models import Issue, IssueComment
from domain_model.github.labels import GitHubLabel
from domain_model.github.repository_client import ClosablePullRequests
from domain_model.github.rest_models import RestPullRequest
from domain_model.github.vocabulary import IssueState, IssueStateReason

from github_workflow.findings import FindingLabel, FindingStage, Priority
from github_workflow.proofs import FindingTest, ProofAttempt, ProofRunner
from github_workflow.settings import WorkflowSettings

# %% an issue board in memory


@dataclass(frozen=True)
class IssuesInMemory(ClosablePullRequests):
    """
    A repository's issues, pull requests and labels, recording every write.
    """

    open_issues: dict[int, Issue] = field(default_factory=dict)
    """
    The open issues, by number.
    """

    present_labels: set[str] = field(default_factory=set)
    """
    The labels the repository carries.
    """

    posted: dict[int, list[IssueComment]] = field(default_factory=dict)
    """
    The comments on each issue, by number, oldest first.
    """

    author: str = WorkflowSettings().owner
    """
    The login every comment added is posted as.
    """

    writes: list[str] = field(default_factory=list)
    """
    Every write to an issue or label, in a word and its arguments.
    """

    pull_requests: dict[int, RestPullRequest] = field(default_factory=dict)
    """
    The pull requests, by number.
    """

    closed_pull_requests: list[int] = field(default_factory=list)
    """
    The pull requests closed, in order.
    """

    descriptions: dict[int, str] = field(default_factory=dict)
    """
    The description each issue was filed with, by number.
    """

    def open_pull_requests(self) -> list[RestPullRequest]:
        return list(self.pull_requests.values())

    def pull_request(self, number: int) -> RestPullRequest:
        return self.pull_requests[number]

    def close_pull_request(self, number: int) -> None:
        self.closed_pull_requests.append(number)

    def labels(self) -> set[str]:
        return set(self.present_labels)

    def create_label(self, label: GitHubLabel) -> None:
        self.writes.append(f"create_label {label}")
        self.present_labels.add(label)

    def open_issue(self, title: str, body: str, labels: Sequence[str]) -> int:
        number = max(self.open_issues, default=0) + 1
        self.open_issues[number] = Issue(number, title, tuple(labels), IssueState.OPEN)
        self.descriptions[number] = body
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
        if number in self.open_issues:
            issue = self.open_issues[number]
            added = tuple(label for label in labels if label not in issue.labels)
            self.open_issues[number] = replace(issue, labels=issue.labels + added)

    def remove_label(self, number: int, label: str) -> None:
        self.writes.append(f"remove_label {number} {label}")
        if number in self.open_issues:
            issue = self.open_issues[number]
            kept = tuple(carried for carried in issue.labels if carried != label)
            self.open_issues[number] = replace(issue, labels=kept)

    def add_comment(self, number: int, body: str) -> str:
        self.writes.append(f"add_comment {number} {body}")
        self.posted.setdefault(number, []).append(IssueComment(self.author, body))
        return ""

    def comments(self, number: int) -> list[IssueComment]:
        return list(self.posted.get(number, []))

    def close_issue(self, number: int, reason: IssueStateReason) -> None:
        self.writes.append(f"close_issue {number} {reason}")

    def set_issue_title(self, number: int, title: str) -> None:
        self.writes.append(f"set_issue_title {number} {title}")

    def set_issue_description(self, number: int, body: str) -> None:
        self.writes.append(f"set_issue_description {number} {body}")


def build_finding(number: int, stage: FindingStage, priority: Priority) -> Issue:
    """:param number: The issue's number.
    :param stage: Where the finding stands.
    :param priority: How urgent it is.
    :return: The finding as an open issue."""
    return Issue(number, f"Finding {number}", (stage, priority), IssueState.OPEN)


def labelled_board(*issues: Issue) -> IssuesInMemory:
    """:param issues: The issues on the board.
    :return: A board holding them, carrying every finding label already."""
    return IssuesInMemory(
        {issue.number: issue for issue in issues}, set(FindingLabel.every_label)
    )


# %% running a finding's test


@dataclass(frozen=True)
class PresetOutcomeRunner(ProofRunner):
    """
    Answers every test with one attempt set in advance, recording the tests it ran.
    """

    outcome: ProofAttempt
    """
    The attempt every test is answered with.
    """

    ran: list[FindingTest] = field(default_factory=list)
    """
    The tests it was asked to run, in order.
    """

    def attempt(self, test: FindingTest) -> ProofAttempt:
        self.ran.append(test)
        return self.outcome
