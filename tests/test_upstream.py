"""
Tests for :mod:`github_workflow.upstream`: the person, and only the person, opens a
fork's pull request on its upstream, linking back to it.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest
from domain_model.git.remotes import RemoteName
from domain_model.git.revisions import BranchName
from domain_model.github.issue_models import IssueComment
from domain_model.github.labels import GitHubLabel
from domain_model.github.repository_client import (
    FollowedFork,
    ForkDetails,
    ProposingFork,
    PullRequestSearch,
)
from domain_model.github.rest_models import RestPullRequest, SearchedPullRequest
from domain_model.github.stack_models import Stack
from domain_model.github.stack_placement import StackPlacement
from domain_model.github.vocabulary import PullRequestState
from domain_model.repository import GitHubAddress, Repository

from github_workflow.exceptions import (
    ForeignRepositoryError,
    ForkBranchDivergedError,
    NotAForkError,
    PersonOnlyCommandError,
    PullRequestNotProposableError,
    UpstreamRemoteNameTakenError,
)
from github_workflow.policy import WritePolicy
from github_workflow.push_hook import PushHook
from github_workflow.report_lines import Tone
from github_workflow.settings import WorkflowSettings
from github_workflow.upstream import (
    ForkMainSync,
    UpstreamLabel,
    UpstreamMergeFollowing,
    UpstreamProposal,
    UpstreamSuggestion,
)

from .pull_requests import pull_request
from .repositories_by_owner import RepositoriesByOwner
from .scratch_github import ScratchGitHub
from .stacked_pull_requests import StackedPullRequestsInMemory
from .test_push_hook import in_claude_code  # noqa: F401  (a fixture)
from .test_work import RetiredInMemory, work  # noqa: F401  (a fixture)

# %% repositories in memory


@dataclass(frozen=True)
class ForkInMemory(ProposingFork):
    """
    A repository with its pull requests, the one it was forked from, its labels, and the
    comments and label sets written on it.
    """

    pull_requests: list[RestPullRequest] = field(default_factory=list)
    """
    Its pull requests.
    """

    forked_from: Repository | None = ScratchGitHub.upstream
    """
    The repository it was forked from.
    """

    trunk: BranchName = BranchName("main")
    """
    Its default branch.
    """

    written: list[str] = field(default_factory=list)
    """
    Every comment and pull request written to it.
    """

    carried: set[str] = field(default_factory=set)
    """
    The labels the repository carries, the ones created here included.
    """

    label_sets: list[tuple[int, list[str]]] = field(default_factory=list)
    """
    Each pull request labelled, with the complete label set it was given.
    """

    def fork_branch_pull_requests(
        self, owner: str, branch: BranchName
    ) -> list[RestPullRequest]:
        return [
            pull_request
            for pull_request in self.pull_requests
            if pull_request.head.branch == branch
            and (pull_request.head.repository or "").startswith(f"{owner}/")
        ]

    def open_fork_pull_request(
        self, owner: str, branch: BranchName, base: BranchName, title: str, body: str
    ) -> RestPullRequest:
        self.written.append(f"open {owner}:{branch} onto {base}: {title} | {body}")
        return pull_request(
            7, branch, repository=f"{owner}/{ScratchGitHub.owned.name}", title=title
        )

    def upstream(self) -> Repository | None:
        return self.forked_from

    def default_branch(self) -> BranchName:
        return self.trunk

    def add_comment(self, number: int, body: str) -> str:
        self.written.append(f"comment {number}: {body}")
        return f"https://github.com/comment/{number}"

    def replace_labels(self, number: int, labels: Sequence[str]) -> None:
        self.label_sets.append((number, list(labels)))

    def labels(self) -> set[str]:
        return set(self.carried)

    def create_label(self, label: GitHubLabel) -> None:
        self.carried.add(label)


def proposal(
    fork: ForkInMemory,
    upstream: ForkInMemory,
    branch: str = "feature",
    *,
    run_by_a_session: bool = False,
    repository: Repository = ScratchGitHub.owned,
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
        lambda named: upstream,
        WorkflowSettings(),
        run_by_a_session,
    )


# %% proposing


def test_the_fork_s_pull_request_is_opened_upstream_linking_back_to_it() -> None:
    local = pull_request(3, "feature", title="Add the thing")
    fork = ForkInMemory([local])
    upstream = ForkInMemory(forked_from=None, trunk=BranchName("develop"))

    proposal(fork, upstream).run()

    assert upstream.written == [
        f"open {ScratchGitHub.owned.owner}:feature onto develop: Add the thing | "
        f"{UpstreamProposal.body_linking(local.url)}"
    ]


def test_the_fork_s_pull_request_is_given_the_upstream_link() -> None:
    fork = ForkInMemory([pull_request(3, "feature")])
    upstream = ForkInMemory(forked_from=None)

    proposal(fork, upstream).run()

    opened = upstream.open_fork_pull_request(
        ScratchGitHub.owned.owner, "feature", "main", "", ""
    )
    assert fork.written == [
        f"comment 3: {UpstreamProposal.comment_linking(opened.url)}"
    ]


def test_the_fork_s_pull_request_is_labelled_as_opened_upstream() -> None:
    fork = ForkInMemory([pull_request(3, "feature")])
    upstream = ForkInMemory(forked_from=None)

    proposal(fork, upstream).run()

    assert fork.label_sets == [(3, [UpstreamLabel.OPENED_UPSTREAM])]


def test_the_fork_s_other_labels_are_kept() -> None:
    local = replace(pull_request(3, "feature"), labels=("ready",))
    fork = ForkInMemory([local])
    upstream = ForkInMemory(forked_from=None)

    proposal(fork, upstream).run()

    assert fork.label_sets == [(3, [*local.labels, UpstreamLabel.OPENED_UPSTREAM])]


@pytest.mark.parametrize("carried", [True, False], ids=["label there", "label made"])
def test_the_label_is_made_only_where_the_fork_lacks_it(carried: bool) -> None:
    fork = ForkInMemory(
        [pull_request(3, "feature")],
        carried={UpstreamLabel.OPENED_UPSTREAM} if carried else set(),
    )
    upstream = ForkInMemory(forked_from=None)

    proposal(fork, upstream).run()

    assert fork.carried == {UpstreamLabel.OPENED_UPSTREAM}


def test_a_refused_proposal_labels_nothing() -> None:
    fork = ForkInMemory([pull_request(3, "feature", state=PullRequestState.CLOSED)])
    upstream = ForkInMemory(forked_from=None)

    with pytest.raises(PullRequestNotProposableError):
        proposal(fork, upstream).run()

    assert (fork.label_sets, fork.carried) == ([], set())


def test_a_claude_code_session_may_not_propose() -> None:
    fork = ForkInMemory([pull_request(3, "feature")])
    upstream = ForkInMemory(forked_from=None)

    with pytest.raises(PersonOnlyCommandError):
        proposal(fork, upstream, run_by_a_session=True).run()

    assert (fork.written, upstream.written) == ([], [])


def test_somebody_else_s_repository_is_not_proposed_from() -> None:
    fork = ForkInMemory([pull_request(3, "feature")])
    upstream = ForkInMemory(forked_from=None)

    with pytest.raises(ForeignRepositoryError):
        proposal(fork, upstream, repository=ScratchGitHub.upstream).run()

    assert upstream.written == []


def test_a_repository_that_is_no_fork_is_not_proposed_from() -> None:
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
) -> None:
    fork = ForkInMemory(fork_pull_requests)
    upstream = ForkInMemory(upstream_pull_requests, forked_from=None)

    with pytest.raises(PullRequestNotProposableError):
        proposal(fork, upstream).run()

    assert upstream.written == []


# %% the suggestion in a draft's description


def test_a_draft_on_a_fork_suggests_the_command_to_the_person() -> None:
    suggestion = UpstreamSuggestion(ForkInMemory(), ScratchGitHub.owned)

    described = suggestion.append_once("What the change does.", "feature")

    assert described.startswith("What the change does.")
    assert (
        UpstreamSuggestion.opening_command(ScratchGitHub.owned, "feature") in described
    )


def test_a_description_ending_with_the_suggestion_keeps_it_once() -> None:
    suggestion = UpstreamSuggestion(ForkInMemory(), ScratchGitHub.owned)
    described = suggestion.append_once("What the change does.", "feature")

    assert suggestion.append_once(described, "feature") == described


def test_a_suggestion_amid_a_description_moves_to_its_end() -> None:
    suggestion = UpstreamSuggestion(ForkInMemory(), ScratchGitHub.owned)
    described = suggestion.append_once("What the change does.", "feature")

    rewritten = suggestion.append_once(f"{described}\nAfter the review.", "feature")

    command = UpstreamSuggestion.opening_command(ScratchGitHub.owned, "feature")
    assert rewritten.count(command) == 1
    assert rewritten.index("After the review.") < rewritten.index(command)


def test_a_draft_on_a_repository_that_is_no_fork_suggests_nothing() -> None:
    suggestion = UpstreamSuggestion(ForkInMemory(forked_from=None), ScratchGitHub.owned)

    described = suggestion.append_once("What the change does.", "feature")

    assert described == "What the change does."


# %% following the upstream


@dataclass(frozen=True)
class ForkOfTheUpstream(ForkDetails):
    """
    A fork, answering which repository it was forked from and nothing else, so a sync
    can write to GitHub only through git, as behind a cloud session's proxy.
    """

    forked_from: Repository | None = ScratchGitHub.upstream
    """
    The repository it was forked from.
    """

    def upstream(self) -> Repository | None:
        return self.forked_from


def give_fork_upstream(
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
    upstream = (
        repositories.root
        / ScratchGitHub.upstream.owner
        / f"{ScratchGitHub.upstream.name}.git"
    )
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
    upstream = (
        repositories.root
        / ScratchGitHub.upstream.owner
        / f"{ScratchGitHub.upstream.name}.git"
    )
    git = work.checkout.git
    return (
        git.run("ls-remote", work.remote.push_url, default).split()[0],
        git.run("ls-remote", str(upstream), default).split()[0],
    )


def test_a_fork_s_main_behind_its_upstream_is_fast_forwarded(
    work: WritePolicy, repositories: RepositoriesByOwner
) -> None:
    """
    Through git alone, as where the proxy refuses GitHub's compares and merge-upstream.
    """
    give_fork_upstream(work, repositories, ahead=2, own=0)

    ForkMainSync(work, ForkOfTheUpstream()).run()

    ours, theirs = default_branch_tips(work, repositories)
    local = work.checkout.git.run("rev-parse", RepositoriesByOwner.default_branch)
    assert (ours, local) == (theirs, theirs)


def test_a_fork_s_main_is_fast_forwarded_past_the_checkout_s_push_hook(
    work: WritePolicy,
    repositories: RepositoriesByOwner,
    in_claude_code: None,  # noqa: F811
) -> None:
    """
    The hook refuses every change to the default branch a session would push.
    """
    give_fork_upstream(work, repositories, ahead=1, own=0)
    PushHook(work.checkout, Path(sys.executable)).install()

    ForkMainSync(work, ForkOfTheUpstream()).run()

    ours, theirs = default_branch_tips(work, repositories)
    assert ours == theirs


def test_a_fork_s_main_up_to_date_is_left_alone(
    work: WritePolicy, repositories: RepositoriesByOwner
) -> None:
    give_fork_upstream(work, repositories, ahead=0, own=0)
    before, _ = default_branch_tips(work, repositories)

    ForkMainSync(work, ForkOfTheUpstream()).run()

    assert default_branch_tips(work, repositories)[0] == before


def test_a_fork_s_main_with_commits_of_its_own_is_refused(
    work: WritePolicy, repositories: RepositoriesByOwner
) -> None:
    """
    It is only ever fast-forwarded: never merged, never forced.
    """
    give_fork_upstream(work, repositories, ahead=2, own=1)
    before, _ = default_branch_tips(work, repositories)

    with pytest.raises(ForkBranchDivergedError):
        ForkMainSync(work, ForkOfTheUpstream()).run()

    assert default_branch_tips(work, repositories)[0] == before


def tracked_tip(work: WritePolicy, remote: str) -> str | None:
    """
    :param work: The rules of a clone of the fork.
    :param remote: A remote's name.
    :return: Where the clone last saw that remote's default branch, ``None`` when it
        never fetched it.
    """
    branch = RepositoriesByOwner.default_branch
    found = work.checkout.git.attempt(
        "rev-parse", "--verify", "--quiet", f"refs/remotes/{remote}/{branch}"
    )
    return found.output if found.succeeded else None


def test_the_upstream_configured_under_another_name_is_fetched_under_it(
    work: WritePolicy, repositories: RepositoriesByOwner
) -> None:
    give_fork_upstream(work, repositories, ahead=1, own=0)
    url = ScratchGitHub.upstream.rooted_clone_url()
    work.checkout.git.run("remote", "add", "parent", url)

    ForkMainSync(work, ForkOfTheUpstream()).run()

    _, theirs = default_branch_tips(work, repositories)
    assert (tracked_tip(work, "parent"), tracked_tip(work, RemoteName.UPSTREAM)) == (
        theirs,
        None,
    )


def test_the_remote_named_upstream_is_preferred_among_those_reaching_it(
    work: WritePolicy, repositories: RepositoriesByOwner
) -> None:
    give_fork_upstream(work, repositories, ahead=1, own=0)
    url = ScratchGitHub.upstream.rooted_clone_url()
    work.checkout.git.run("remote", "add", "parent", url)
    work.checkout.git.run("remote", "add", RemoteName.UPSTREAM, url)

    ForkMainSync(work, ForkOfTheUpstream()).run()

    _, theirs = default_branch_tips(work, repositories)
    assert (tracked_tip(work, RemoteName.UPSTREAM), tracked_tip(work, "parent")) == (
        theirs,
        None,
    )


def test_a_remote_named_upstream_reaching_another_repository_is_refused(
    work: WritePolicy, repositories: RepositoriesByOwner
) -> None:
    give_fork_upstream(work, repositories, ahead=1, own=0)
    other = Repository(RepositoriesByOwner.foreign_owner, "elsewhere")
    work.checkout.git.run(
        "remote", "add", RemoteName.UPSTREAM, other.rooted_clone_url()
    )

    with pytest.raises(UpstreamRemoteNameTakenError):
        ForkMainSync(work, ForkOfTheUpstream()).run()

    assert tracked_tip(work, RemoteName.UPSTREAM) is None


def test_a_repository_that_is_no_fork_follows_no_upstream(work: WritePolicy) -> None:
    with pytest.raises(NotAForkError):
        ForkMainSync(work, ForkOfTheUpstream(forked_from=None)).run()


# %% following merges upstream


@dataclass(frozen=True)
class UpstreamSearchInMemory(PullRequestSearch):
    """
    The upstream's pull requests, found by the branch they were opened from.
    """

    found: dict[str, list[SearchedPullRequest]]
    """
    The pull requests opened from each branch.
    """

    def search_branch_pull_requests(
        self, author: str, branch: BranchName
    ) -> list[SearchedPullRequest]:
        return self.found.get(branch, [])


@dataclass(frozen=True)
class OpenedUpstreamPullRequests(StackedPullRequestsInMemory, FollowedFork):
    """
    The stand-in, a fork of :attr:`ScratchGitHub.upstream` on the default branch
    ``main``, with some pull requests labelled as opened upstream.
    """

    opened_upstream: frozenset[int] = frozenset()
    """
    The pull requests labelled so.
    """

    merged: frozenset[int] = frozenset()
    """
    The pull requests the fork has merged.
    """

    linked_upstream: int = 9
    """
    The upstream pull request each one opened upstream links to in its comment.
    """

    link_author: str = ScratchGitHub.owned.owner
    """
    Who posted that comment.
    """

    def comments(self, number: int) -> list[IssueComment]:
        if number not in self.opened_upstream:
            return []
        url = ScratchGitHub.upstream.pull_request_url(self.linked_upstream)
        return [IssueComment(self.link_author, UpstreamProposal.comment_linking(url))]

    def open_pull_requests(self) -> list[RestPullRequest]:
        return [
            pull_request
            for pull_request in super().open_pull_requests()
            if not pull_request.merged
        ]

    def pull_request(self, number: int) -> RestPullRequest:
        labels = (
            (UpstreamLabel.OPENED_UPSTREAM,) if number in self.opened_upstream else ()
        )
        merged = number in self.merged
        return replace(
            super().pull_request(number),
            labels=labels,
            merged=merged,
            state=PullRequestState.CLOSED if merged else PullRequestState.OPEN,
        )

    def upstream(self) -> Repository | None:
        return ScratchGitHub.upstream

    def default_branch(self) -> BranchName:
        return BranchName("main")


def build_following(
    found: dict[str, list[SearchedPullRequest]],
    merged: frozenset[int] = frozenset(),
    opened_upstream: frozenset[int] = frozenset({1}),
    link_author: str = ScratchGitHub.owned.owner,
) -> tuple[UpstreamMergeFollowing, StackedPullRequestsInMemory, RetiredInMemory]:
    """
    :param found: The upstream's pull requests, by the branch they were opened from.
    :param merged: The pull requests the fork has merged already.
    :param opened_upstream: The pull requests labelled as opened upstream, each
        linking to the upstream's #9.
    :param link_author: Who posted the comments linking them.
    :return: The section over a fork whose #2 is stacked on #1; the fork's pull
        requests; and what was closed.
    """
    fork = OpenedUpstreamPullRequests(
        {1: "main", 2: StackedPullRequestsInMemory.name_branch(1)},
        opened_upstream=opened_upstream,
        merged=merged,
        link_author=link_author,
    )
    fork.existing_stacks.append(Stack(7, "main", True, fork.build_stack([1, 2])))
    retired = RetiredInMemory()
    section = UpstreamMergeFollowing(
        ScratchGitHub.owned.owner,
        fork,
        lambda upstream: UpstreamSearchInMemory(found),
        retired,
        StackPlacement(fork),
    )
    return section, fork, retired


def test_a_pull_request_merged_upstream_is_closed_and_its_stack_moved_on() -> None:
    merged = SearchedPullRequest(
        9, ScratchGitHub.upstream.pull_request_url(9), "2026-11-07T10:00:00Z"
    )
    section, fork, retired = build_following({"branch-1": [merged]})

    [line] = section.lines()

    assert (retired.retired, fork.bases[2], line.tone) == (
        [(1, f"Merged upstream as {ScratchGitHub.upstream.pull_request_url(9)}.")],
        "main",
        Tone.ACTION,
    )


def test_a_pull_request_still_open_upstream_is_left_alone() -> None:
    open_upstream = SearchedPullRequest(
        9, ScratchGitHub.upstream.pull_request_url(9), None
    )
    section, fork, retired = build_following({"branch-1": [open_upstream]})

    assert (section.lines(), retired.retired, fork.writes) == ([], [], [])


def test_an_older_merged_pull_request_from_the_same_branch_closes_nothing() -> None:
    """
    A branch name used again: only the upstream pull request the fork's links to counts.
    """
    still_open = SearchedPullRequest(
        9, ScratchGitHub.upstream.pull_request_url(9), None
    )
    older = SearchedPullRequest(
        5, ScratchGitHub.upstream.pull_request_url(5), "2026-01-01T10:00:00Z"
    )
    section, fork, retired = build_following({"branch-1": [still_open, older]})

    assert (section.lines(), retired.retired, fork.writes) == ([], [], [])


def test_a_link_somebody_else_posted_is_not_followed() -> None:
    merged = SearchedPullRequest(
        9, ScratchGitHub.upstream.pull_request_url(9), "2026-11-07T10:00:00Z"
    )
    section, fork, retired = build_following(
        {"branch-1": [merged]}, link_author="somebody-else"
    )

    assert (section.lines(), retired.retired, fork.writes) == ([], [], [])


def test_what_is_stacked_on_a_pull_request_the_fork_merged_already_is_moved_on() -> (
    None
):
    merged = SearchedPullRequest(
        9, ScratchGitHub.upstream.pull_request_url(9), "2026-11-07T10:00:00Z"
    )
    section, fork, retired = build_following(
        {"branch-1": [merged]}, merged=frozenset({1})
    )

    [line] = section.lines()

    assert (retired.retired, fork.writes, line.tone) == (
        [],
        ["unstack 7", "set_base 2 main"],
        Tone.ACTION,
    )


def test_what_is_stacked_on_a_merged_pull_request_never_opened_upstream_is_left_alone() -> (
    None
):
    section, fork, retired = build_following(
        {}, merged=frozenset({1}), opened_upstream=frozenset()
    )

    assert (section.lines(), retired.retired, fork.writes) == ([], [], [])
