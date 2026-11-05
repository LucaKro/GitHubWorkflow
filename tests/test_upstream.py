"""
Tests for :mod:`github_workflow.upstream`: the person, and only the person, opens a
fork's pull request on its upstream, linking back to it.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from basstler_domain_model.github.repository_client import (
    Commenter,
    ForkDetails,
    PullRequestsFromForks,
    RepositoryDetails,
)
from basstler_domain_model.github.rest_models import RestPullRequest
from basstler_domain_model.github.vocabulary import PullRequestState
from basstler_domain_model.repository import GitHubAddress, Repository

from github_workflow.exceptions import (
    ForeignRepositoryError,
    ForkBranchDivergedError,
    NotAForkError,
    PersonOnlyCommandError,
    PullRequestNotProposableError,
)
from github_workflow.settings import WorkflowSettings
from github_workflow.policy import WritePolicy
from github_workflow.push_hook import PushHook
from github_workflow.upstream import ForkMainSync, UpstreamProposal, UpstreamSuggestion

from .pull_requests import REPOSITORY, pull_request
from .repositories_by_owner import RepositoriesByOwner
from .test_push_hook import in_claude_code  # noqa: F401  (a fixture)
from .test_work import work  # noqa: F401  (a fixture)

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


def test_somebody_else_s_repository_is_not_proposed_from():
    fork = ForkInMemory([pull_request(3, "feature")])
    upstream = ForkInMemory(forked_from=None)

    with pytest.raises(ForeignRepositoryError):
        proposal(fork, upstream, repository=UPSTREAM).run()

    assert upstream.written == []


def test_a_repository_that_is_no_fork_is_not_proposed_from():
    fork = ForkInMemory([pull_request(3, "feature")], forked_from=None)
    upstream = ForkInMemory(forked_from=None)

    with pytest.raises(NotAForkError):
        proposal(fork, upstream).run()

    assert upstream.written == []


@pytest.mark.parametrize(
    "fork_pull_requests, upstream_pull_requests",
    [
        ([], []),
        ([pull_request(3, "feature", state=PullRequestState.CLOSED)], []),
        ([pull_request(3, "feature", state=PullRequestState.MERGED)], []),
        ([pull_request(3, "feature", base="lower")], []),
        ([pull_request(3, "feature")], [pull_request(9, "feature")]),
    ],
    ids=["no pull request", "closed", "merged", "stacked", "already upstream"],
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


def test_a_description_ending_with_the_suggestion_keeps_it_once():
    suggestion = UpstreamSuggestion(ForkInMemory(), FORK)
    described = suggestion.appended_to("What the change does.", "feature")

    assert suggestion.appended_to(described, "feature") == described


def test_a_suggestion_amid_a_description_moves_to_its_end():
    suggestion = UpstreamSuggestion(ForkInMemory(), FORK)
    described = suggestion.appended_to("What the change does.", "feature")

    rewritten = suggestion.appended_to(f"{described}\nAfter the review.", "feature")

    command = UpstreamSuggestion.command_for(FORK, "feature")
    assert rewritten.count(command) == 1
    assert rewritten.index("After the review.") < rewritten.index(command)


def test_a_draft_on_a_repository_that_is_no_fork_suggests_nothing():
    suggestion = UpstreamSuggestion(ForkInMemory(forked_from=None), FORK)

    described = suggestion.appended_to("What the change does.", "feature")

    assert described == "What the change does."


# %% following the upstream


@dataclass(frozen=True)
class ForkOfTheUpstream(ForkDetails):
    """
    A fork, answering which repository it was forked from and nothing else, so a sync
    can write to GitHub only through git, as behind a cloud session's proxy.
    """

    forked_from: Repository | None = UPSTREAM
    """
    The repository it was forked from.
    """

    def upstream(self) -> Repository | None:
        return self.forked_from


def with_upstream(
    work: WritePolicy, repositories: RepositoriesByOwner, *, ahead: int, own: int
) -> None:
    """
    Give the fork of a clone an upstream sharing its default branch, which then gains
    commits the fork lacks, while the fork's default branch gains commits of its own;
    the clone reaches the upstream's GitHub address in the scratch repositories.

    :param work: The rules of a clone of the fork.
    :param repositories: The scratch repositories.
    :param ahead: The commits the upstream's branch gains.
    :param own: The commits the fork's branch gains.
    """
    upstream = repositories.root / UPSTREAM.owner / f"{UPSTREAM.name}.git"
    default = RepositoriesByOwner.default_branch
    git = work.checkout.git
    git.run("init", "--quiet", "--bare", f"--initial-branch={default}", str(upstream))
    git.run(
        "push",
        "--quiet",
        str(upstream),
        f"refs/remotes/{work.remote.name}/{default}:refs/heads/{default}",
    )
    for repository, commits, name in ((upstream, ahead, "theirs"), (None, own, "own")):
        if not commits:
            continue
        url = f"file://{repository}" if repository else work.remote.push_url
        writer = repositories.clone(url, f"{name}-writer").git
        for number in range(commits):
            message = f"{name} {number}"
            writer.run("commit", "--quiet", "--allow-empty", "--message", message)
        target = str(repository) if repository else "origin"
        writer.run("push", "--quiet", target, f"HEAD:refs/heads/{default}")
    git.run(
        "config", f"url.file://{repositories.root}/.insteadOf", f"{GitHubAddress.WEB}/"
    )


def default_branch_tips(
    work: WritePolicy, repositories: RepositoriesByOwner
) -> tuple[str, str]:
    """
    :param work: The rules of a clone of the fork.
    :param repositories: The scratch repositories.
    :return: Where the fork's default branch is on GitHub, and where the upstream's is.
    """
    default = RepositoriesByOwner.default_branch
    upstream = repositories.root / UPSTREAM.owner / f"{UPSTREAM.name}.git"
    git = work.checkout.git
    return (
        git.run("ls-remote", work.remote.push_url, default).split()[0],
        git.run("ls-remote", str(upstream), default).split()[0],
    )


def test_a_fork_s_main_behind_its_upstream_is_fast_forwarded(
    work: WritePolicy, repositories: RepositoriesByOwner
):
    """
    Through git alone, as where the proxy refuses GitHub's compares and merge-upstream.
    """
    with_upstream(work, repositories, ahead=2, own=0)

    ForkMainSync(work, ForkOfTheUpstream()).run()

    ours, theirs = default_branch_tips(work, repositories)
    local = work.checkout.git.commit_at(RepositoriesByOwner.default_branch)
    assert (ours, local) == (theirs, theirs)


def test_a_fork_s_main_is_fast_forwarded_past_the_checkout_s_push_hook(
    work: WritePolicy,
    repositories: RepositoriesByOwner,
    in_claude_code: None,  # noqa: F811
):
    """
    The hook refuses every change to the default branch a session would push.
    """
    with_upstream(work, repositories, ahead=1, own=0)
    PushHook(work.checkout, Path(sys.executable)).install()

    ForkMainSync(work, ForkOfTheUpstream()).run()

    ours, theirs = default_branch_tips(work, repositories)
    assert ours == theirs


def test_a_fork_s_main_up_to_date_is_left_alone(
    work: WritePolicy, repositories: RepositoriesByOwner
):
    with_upstream(work, repositories, ahead=0, own=0)
    before, _ = default_branch_tips(work, repositories)

    ForkMainSync(work, ForkOfTheUpstream()).run()

    assert default_branch_tips(work, repositories)[0] == before


def test_a_fork_s_main_with_commits_of_its_own_is_refused(
    work: WritePolicy, repositories: RepositoriesByOwner
):
    """
    It is only ever fast-forwarded: never merged, never forced.
    """
    with_upstream(work, repositories, ahead=2, own=1)
    before, _ = default_branch_tips(work, repositories)

    with pytest.raises(ForkBranchDivergedError):
        ForkMainSync(work, ForkOfTheUpstream()).run()

    assert default_branch_tips(work, repositories)[0] == before


def test_a_repository_that_is_no_fork_follows_no_upstream(work: WritePolicy):
    with pytest.raises(NotAForkError):
        ForkMainSync(work, ForkOfTheUpstream(forked_from=None)).run()
