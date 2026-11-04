"""
Tests for :mod:`github_workflow.upstream`: the person, and only the person, opens a
fork's pull request on its upstream, linking back to it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from basstler_domain_model.github.repository_client import (
    Commenter,
    ForkDetails,
    PullRequestsFromForks,
    RepositoryDetails,
)
from basstler_domain_model.github.rest_models import RestPullRequest
from basstler_domain_model.github.vocabulary import PullRequestState
from basstler_domain_model.repository import Repository

from github_workflow.exceptions import (
    NotOwnersForkError,
    PersonOnlyCommandError,
    PullRequestNotProposableError,
)
from github_workflow.settings import WorkflowSettings
from github_workflow.upstream import UpstreamProposal, UpstreamSuggestion

from .pull_requests import REPOSITORY, pull_request

FORK = Repository.parse(REPOSITORY)
"""
The owner's fork every proposal here starts from.
"""

UPSTREAM = Repository("an-upstream-owner", FORK.name)
"""
The repository the fork was forked from.
"""

# %% repositories in memory


@dataclass(frozen=True)
class ForkInMemory(PullRequestsFromForks, ForkDetails, RepositoryDetails, Commenter):
    """
    A repository with its pull requests, the one it was forked from, and the comments
    written on it.
    """

    pull_requests: list[RestPullRequest] = field(default_factory=list)
    """
    Its pull requests.
    """

    forked_from: Repository | None = UPSTREAM
    """
    The repository it was forked from.
    """

    trunk: str = "main"
    """
    Its default branch.
    """

    written: list[str] = field(default_factory=list)
    """
    Every comment and pull request written to it.
    """

    def pull_requests_from(self, owner: str, branch: str) -> list[RestPullRequest]:
        return [
            pull_request
            for pull_request in self.pull_requests
            if pull_request.head.branch == branch
            and (pull_request.head.repository or "").startswith(f"{owner}/")
        ]

    def open_pull_request_from(
        self, owner: str, branch: str, base: str, title: str, body: str
    ) -> RestPullRequest:
        self.written.append(f"open {owner}:{branch} onto {base}: {title} | {body}")
        return pull_request(7, branch, repository=f"{owner}/{FORK.name}", title=title)

    def upstream(self) -> Repository | None:
        return self.forked_from

    def default_branch(self) -> str:
        return self.trunk

    def add_comment(self, number: int, body: str) -> str:
        self.written.append(f"comment {number}: {body}")
        return f"https://github.com/comment/{number}"


def proposal(
    fork: ForkInMemory,
    upstream: ForkInMemory,
    branch: str = "feature",
    *,
    run_by_a_session: bool = False,
    repository: Repository = FORK,
) -> UpstreamProposal:
    """
    :param fork: The owner's fork.
    :param upstream: The repository it was forked from.
    :param branch: The fork's branch to propose.
    :param run_by_a_session: Whether a Claude Code session runs the command.
    :param repository: The repository named on the command line.
    :return: The proposal.
    """
    return UpstreamProposal(
        repository,
        branch,
        fork,
        fork,
        fork,
        fork,
        lambda named: upstream,
        lambda named: upstream,
        WorkflowSettings(),
        run_by_a_session,
    )


# %% proposing


def test_the_fork_s_pull_request_is_opened_upstream_linking_back_to_it():
    local = pull_request(3, "feature", title="Add the thing")
    fork = ForkInMemory([local])
    upstream = ForkInMemory(forked_from=None, trunk="develop")

    proposal(fork, upstream).run()

    assert upstream.written == [
        f"open {FORK.owner}:feature onto develop: Add the thing | "
        f"{UpstreamProposal.body_linking(local.url)}"
    ]


def test_the_fork_s_pull_request_is_given_the_upstream_link():
    fork = ForkInMemory([pull_request(3, "feature")])
    upstream = ForkInMemory(forked_from=None)

    proposal(fork, upstream).run()

    opened = upstream.open_pull_request_from(FORK.owner, "feature", "main", "", "")
    assert fork.written == [
        f"comment 3: {UpstreamProposal.comment_linking(opened.url)}"
    ]


def test_a_claude_code_session_may_not_propose():
    fork = ForkInMemory([pull_request(3, "feature")])
    upstream = ForkInMemory(forked_from=None)

    with pytest.raises(PersonOnlyCommandError):
        proposal(fork, upstream, run_by_a_session=True).run()

    assert (fork.written, upstream.written) == ([], [])


@pytest.mark.parametrize(
    "repository, forked_from",
    [(UPSTREAM, UPSTREAM), (FORK, None)],
    ids=["somebody else's", "no fork"],
)
def test_only_a_fork_of_the_owner_s_is_proposed_from(
    repository: Repository, forked_from: Repository | None
):
    fork = ForkInMemory([pull_request(3, "feature")], forked_from=forked_from)
    upstream = ForkInMemory(forked_from=None)

    with pytest.raises(NotOwnersForkError):
        proposal(fork, upstream, repository=repository).run()

    assert upstream.written == []


@pytest.mark.parametrize(
    "fork_pull_requests, upstream_pull_requests",
    [
        ([], []),
        ([pull_request(3, "feature", state=PullRequestState.CLOSED)], []),
        ([pull_request(3, "feature", base="lower")], []),
        ([pull_request(3, "feature")], [pull_request(9, "feature")]),
    ],
    ids=["no pull request", "closed", "stacked", "already upstream"],
)
def test_a_pull_request_that_cannot_go_upstream_is_refused(
    fork_pull_requests: list[RestPullRequest],
    upstream_pull_requests: list[RestPullRequest],
):
    fork = ForkInMemory(fork_pull_requests)
    upstream = ForkInMemory(upstream_pull_requests, forked_from=None)

    with pytest.raises(PullRequestNotProposableError):
        proposal(fork, upstream).run()

    assert upstream.written == []


# %% the suggestion in a draft's description


def test_a_draft_on_a_fork_suggests_the_command_to_the_person():
    suggestion = UpstreamSuggestion(ForkInMemory(), FORK)

    described = suggestion.appended_to("What the change does.", "feature")

    assert described.startswith("What the change does.")
    assert UpstreamSuggestion.command_for(FORK, "feature") in described


def test_a_draft_on_a_repository_that_is_no_fork_suggests_nothing():
    suggestion = UpstreamSuggestion(ForkInMemory(forked_from=None), FORK)

    described = suggestion.appended_to("What the change does.", "feature")

    assert described == "What the change does."
