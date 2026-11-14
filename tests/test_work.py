"""
Tests for :mod:`github_workflow.work`: every write a session makes, and every write the
policy refuses before it is attempted.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest
from domain_model.class_property import classproperty
from domain_model.environment import GitIdentityVariable
from domain_model.git.commands import GitCommandRunner
from domain_model.git.exceptions import GitCommandFailed
from domain_model.git.revisions import BranchName
from domain_model.git.working_tree import Merge, WorkingTree
from domain_model.github.exceptions import StackContinuesAboveError
from domain_model.github.repository_client import (
    BranchStacks,
    PullRequestReader,
    PullRequestsFromForks,
    RepositoryDetails,
    Reviewer,
)
from domain_model.github.rest_models import RestPullRequest
from domain_model.github.stack_models import Stack
from domain_model.github.stack_placement import StackPlacement
from domain_model.github.vocabulary import ClosingKeyword, PullRequestState
from domain_model.repository import Repository

import github_workflow
from github_workflow.checkout import ProjectCheckout
from github_workflow.command_line import RunnableCommand, WorkflowCommand
from github_workflow.environment import WorkflowVariable
from github_workflow.exceptions import (
    ForeignPullRequestError,
    AssistantCreditError,
    BranchDeletedFromGitHubError,
    BranchNotPushedError,
    ConflictMarkersLeftError,
    DefaultBranchWriteError,
    DetachedHeadError,
    DraftUnfinishedError,
    MergeConflictError,
    MergeInProgressError,
    NoMergeInProgressError,
    NothingToDescribeError,
    PullRequestNotOpenError,
    PushRefusedError,
    StackedBranchMergeError,
    UnbuildablePullRequestError,
    UnknownPluginDataError,
    UnpushedCommitsError,
    UnreplaceablePullRequestError,
    UnresolvedConflictError,
)
from github_workflow.locations import PluginDataDirectory
from github_workflow.policy import Attribution, WritePolicy
from github_workflow.push_hook import PushHook
from github_workflow.remotes import OwnedRemotes
from github_workflow.session import WorkflowSession
from github_workflow.settings import WorkflowSettings
from github_workflow.work import (
    PullRequestComment,
    PullRequestReview,
    BaseMerge,
    BranchStart,
    BranchSwitch,
    BranchSync,
    ClosingLines,
    CommitWork,
    DescriptionEnding,
    DescriptionRewrite,
    DraftOpening,
    LocalBranchFollowing,
    MergeAbort,
    MergeCompletion,
    PullRequestMerge,
    PullRequestOpenedLabelling,
    PullRequestRetirement,
    PushWork,
    Replacement,
    RepositoryCloning,
)
from github_workflow.workflow_step import SessionLog

from .issues_in_memory import IssuesInMemory
from .pull_requests import pull_request
from .repositories_by_owner import RepositoriesByOwner
from .scratch_github import ScratchGitHub
from .stacked_pull_requests import (
    DraftsAndStacksInMemory,
    DraftsInMemory,
    StackedPullRequestsInMemory,
)
from .test_push_hook import in_claude_code  # noqa: F401  (a fixture)

# %% helpers


class DefaultBranchOfTheScratchRepositories(RepositoryDetails):
    """
    Answers the default branch every scratch repository starts with.
    """

    def default_branch(self) -> BranchName:
        return RepositoriesByOwner.default_branch


def build_write_policy(
    checkout: ProjectCheckout, settings: WorkflowSettings
) -> WritePolicy:
    """
    :param checkout: A clone of the owner's repository.
    :param settings: The workflow's settings.
    :return: The rules writes from it pass.
    """
    remote = OwnedRemotes.read(checkout.git, settings).chosen
    return WritePolicy(checkout, remote, DefaultBranchOfTheScratchRepositories())


def write(checkout: ProjectCheckout, name: str) -> Path:
    """
    :param checkout: The checkout to write in.
    :param name: The file's name, which is also its text.
    :return: The file, relative to the checkout.
    """
    (checkout.root / name).write_text(f"{name}\n")
    return Path(name)


def last_message(git: GitCommandRunner) -> str:
    """:param git: A checkout.
    :return: The full message of its last commit."""
    return git.run("log", "--max-count=1", "--format=%B")


@pytest.fixture
def work(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
) -> WritePolicy:
    """:return: The rules of a fresh clone of the owner's repository, on a pushed work
    branch with one commit."""
    policy = build_write_policy(repositories.clone(owned_url, "work"), settings)
    BranchStart(policy, BranchName("feature")).run()
    CommitWork(policy, "Add a file", [write(policy.checkout, "a.txt")]).run()
    PushWork(policy).run()
    return policy


# %% branches


def test_a_work_branch_starts_from_github_s_default_branch(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
) -> None:
    policy = build_write_policy(repositories.clone(owned_url, "work"), settings)

    BranchStart(policy, BranchName("feature")).run()

    git = policy.checkout.git
    assert git.run("branch", "--show-current") == "feature"
    assert git.run("rev-parse", "HEAD") == git.run(
        "rev-parse",
        policy.remote.branch(policy.default_branch).tracking_branch.revision_name,
    )


def test_a_work_branch_starts_on_another_branch_when_asked(work: WritePolicy) -> None:
    git = work.checkout.git

    BranchStart(work, BranchName("upper"), BranchName("feature")).run()

    assert git.run("rev-parse", "upper") == git.run("rev-parse", "feature")


def test_a_work_branch_starts_on_a_local_branch_github_does_not_have(
    work: WritePolicy,
) -> None:
    git = work.checkout.git
    BranchStart(work, BranchName("unpushed")).run()
    CommitWork(work, "Add b", [write(work.checkout, "b.txt")]).run()

    BranchStart(work, BranchName("upper"), BranchName("unpushed")).run()

    assert git.run("rev-parse", "upper") == git.run("rev-parse", "unpushed")


def advance_github_s_default_branch(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
) -> str:
    """:return: The commit GitHub's default branch moved on to, pushed from a second
    clone."""
    mover = build_write_policy(repositories.clone(owned_url, "mover"), settings)
    git = mover.checkout.git
    write(mover.checkout, "moved.txt")
    git.run("add", "moved.txt")
    git.run("commit", "--quiet", "--message", "Move on")
    default = mover.remote.branch(RepositoriesByOwner.default_branch)
    git.run("push", "--quiet", default.remote.name, f"HEAD:{default.reference}")
    return git.run("rev-parse", "HEAD")


def test_starting_from_the_default_branch_fast_forwards_the_local_one(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
) -> None:
    policy = build_write_policy(repositories.clone(owned_url, "work"), settings)
    moved = advance_github_s_default_branch(repositories, owned_url, settings)

    BranchStart(policy, BranchName("feature")).run()

    assert policy.checkout.git.run("rev-parse", policy.default_branch) == moved


def test_a_local_default_branch_with_commits_of_its_own_is_kept(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
) -> None:
    policy = build_write_policy(repositories.clone(owned_url, "work"), settings)
    git = policy.checkout.git
    write(policy.checkout, "own.txt")
    git.run("add", "own.txt")
    git.run("commit", "--quiet", "--message", "Own")
    own = git.run("rev-parse", "HEAD")
    advance_github_s_default_branch(repositories, owned_url, settings)

    BranchStart(policy, BranchName("feature")).run()

    assert git.run("rev-parse", policy.default_branch) == own


def test_starting_from_another_branch_leaves_the_local_default_branch_alone(
    work: WritePolicy,
    repositories: RepositoriesByOwner,
    owned_url: str,
    settings: WorkflowSettings,
) -> None:
    git = work.checkout.git
    before = git.run("rev-parse", work.default_branch)
    advance_github_s_default_branch(repositories, owned_url, settings)

    BranchStart(work, BranchName("upper"), BranchName("feature")).run()

    assert git.run("rev-parse", work.default_branch) == before


def test_switching_checks_out_the_branch(work: WritePolicy) -> None:
    BranchSwitch(work, RepositoriesByOwner.default_branch).run()

    assert (
        work.checkout.git.run("branch", "--show-current")
        == RepositoriesByOwner.default_branch
    )


def test_switching_to_a_branch_only_github_has_checks_it_out(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
) -> None:
    session = build_write_policy(repositories.clone(owned_url, "session"), settings)
    elsewhere = build_write_policy(repositories.clone(owned_url, "elsewhere"), settings)
    BranchStart(elsewhere, BranchName("pushed-elsewhere")).run()
    CommitWork(elsewhere, "Add a file", [write(elsewhere.checkout, "a.txt")]).run()
    PushWork(elsewhere).run()

    BranchSwitch(session, BranchName("pushed-elsewhere")).run()

    git = session.checkout.git
    assert (git.run("branch", "--show-current"), git.run("rev-parse", "HEAD")) == (
        "pushed-elsewhere",
        elsewhere.checkout.git.run("rev-parse", "HEAD"),
    )


def test_switching_to_a_branch_github_lacks_checks_out_the_local_one(
    work: WritePolicy,
) -> None:
    BranchStart(work, BranchName("unpushed")).run()
    BranchSwitch(work, RepositoriesByOwner.default_branch).run()

    BranchSwitch(work, BranchName("unpushed")).run()

    assert work.checkout.git.run("branch", "--show-current") == "unpushed"


# %% committing


def test_a_commit_acknowledges_the_assistant_s_help(work: WritePolicy) -> None:
    CommitWork(work, "Add b", [write(work.checkout, "b.txt")]).run()

    assert last_message(work.checkout.git) == f"Add b\n\n{Attribution.ACKNOWLEDGEMENT}"


def test_a_commit_already_acknowledging_it_is_left_as_it_is(work: WritePolicy) -> None:
    message = f"Add b\n\n{Attribution.ACKNOWLEDGEMENT}"

    CommitWork(work, message, [write(work.checkout, "b.txt")]).run()

    assert last_message(work.checkout.git) == message


def test_a_commit_crediting_an_assistant_as_co_author_is_refused(
    work: WritePolicy,
) -> None:
    message = "Add b\n\nCo-Authored-By: Claude <noreply@anthropic.com>"
    before = work.checkout.git.run("rev-parse", "HEAD")

    with pytest.raises(AssistantCreditError):
        CommitWork(work, message, [write(work.checkout, "b.txt")]).run()

    assert work.checkout.git.run("rev-parse", "HEAD") == before


def test_a_commit_authored_as_an_assistant_is_refused(work: WritePolicy) -> None:
    work.checkout.git.run("config", "user.email", "noreply@anthropic.com")

    with pytest.raises(AssistantCreditError):
        CommitWork(work, "Add b", [write(work.checkout, "b.txt")]).run()


def test_a_commit_committed_as_an_assistant_is_refused(
    work: WritePolicy, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(GitIdentityVariable.COMMITTER_EMAIL, "noreply@anthropic.com")
    before = work.checkout.git.run("rev-parse", "HEAD")

    with pytest.raises(AssistantCreditError):
        CommitWork(work, "Add b", [write(work.checkout, "b.txt")]).run()

    assert work.checkout.git.run("rev-parse", "HEAD") == before


def test_a_person_named_like_the_assistant_may_commit(work: WritePolicy) -> None:
    work.checkout.git.run("config", "user.name", "Claude Monet")
    work.checkout.git.run("config", "user.email", "claude.monet@example.com")

    CommitWork(work, "Add b", [write(work.checkout, "b.txt")]).run()

    assert work.checkout.git.run("log", "-1", "--format=%an") == "Claude Monet"


def test_a_commit_needs_no_access_to_github(work: WritePolicy, tmp_path: Path) -> None:
    """
    Committing is local: without a token, and so without GitHub's API, it still runs.
    """
    write(work.checkout, "b.txt")

    finished = subprocess.run(
        [sys.executable, "-m", github_workflow.__name__, WorkflowCommand.COMMIT]
        + ["-m", "Add b", "b.txt"],
        cwd=work.checkout.root,
        capture_output=True,
        text=True,
        env={"PATH": os.environ["PATH"], "HOME": str(tmp_path / "home")},
    )

    assert finished.returncode == 0, finished.stderr
    assert work.checkout.git.run("log", "-1", "--format=%s") == "Add b"


def test_a_commit_on_the_default_branch_is_refused(work: WritePolicy) -> None:
    BranchSwitch(work, RepositoriesByOwner.default_branch).run()

    with pytest.raises(DefaultBranchWriteError):
        CommitWork(work, "Add b", [write(work.checkout, "b.txt")]).run()


def test_a_commit_without_a_branch_is_refused(work: WritePolicy) -> None:
    work.checkout.git.run("switch", "--quiet", "--detach")

    with pytest.raises(DetachedHeadError):
        CommitWork(work, "Add b", [write(work.checkout, "b.txt")]).run()


# %% pushing


def test_a_pushed_branch_is_on_the_owner_s_repository(work: WritePolicy) -> None:
    branch = work.remote.branch(BranchName("feature"))

    assert branch.exists()


def test_a_pushed_branch_tracks_its_copy_on_the_owner_s_repository(
    work: WritePolicy,
) -> None:
    tracked = work.checkout.git.run("rev-parse", "--abbrev-ref", "feature@{upstream}")

    assert tracked == f"{work.remote.name}/feature"


def test_pushing_the_default_branch_is_refused(work: WritePolicy) -> None:
    BranchSwitch(work, RepositoriesByOwner.default_branch).run()

    with pytest.raises(DefaultBranchWriteError):
        PushWork(work).run()


def test_a_push_github_would_have_to_be_forced_to_take_is_refused(
    work: WritePolicy,
    repositories: RepositoriesByOwner,
    owned_url: str,
    settings: WorkflowSettings,
) -> None:
    other_clone_pushing(repositories, owned_url, settings)
    CommitWork(work, "Add b", [write(work.checkout, "b.txt")]).run()

    with pytest.raises(PushRefusedError):
        PushWork(work).run()


def test_a_push_from_somebody_else_s_repository_is_refused_before_it_is_tried(
    repositories: RepositoriesByOwner, foreign_url: str
) -> None:
    checkout = repositories.clone(foreign_url, "theirs")
    before = repositories.branches(foreign_url)

    finished = subprocess.run(
        [sys.executable, "-m", github_workflow.__name__, WorkflowCommand.PUSH],
        cwd=checkout.root,
        capture_output=True,
        text=True,
    )

    assert finished.returncode != 0
    assert repositories.branches(foreign_url) == before


# %% draft pull requests


@dataclass(frozen=True)
class RetiredInMemory(PullRequestRetirement):
    """
    Records every pull request closed, with why.
    """

    retired: list[tuple[int, str]] = field(default_factory=list)
    """
    Each pull request closed, and the reason given.
    """

    def retire(self, number: int, reason: str) -> None:
        self.retired.append((number, reason))


@dataclass(frozen=True)
class EntriesInMemory(SessionLog):
    """
    Records every entry made in the session log.
    """

    entries: list[str] = field(default_factory=list)
    """
    Each entry, in order.
    """

    def enter(self, action: str) -> None:
        self.entries.append(action)


def draft(
    policy: WritePolicy, github: DraftsAndStacksInMemory, below: int | None
) -> DraftOpening:
    """
    :param policy: The rules of the checkout.
    :param github: The pull requests and stacks.
    :param below: The pull request to stack on, if any.
    :return: The step opening a draft.
    """
    return DraftOpening(
        policy,
        github,
        StackPlacement(github),
        PullRequestOpenedLabelling(IssuesInMemory()),
        "A title",
        "A body",
        below,
    )


def test_a_draft_targets_the_default_branch(work: WritePolicy) -> None:
    github = DraftsAndStacksInMemory({})

    draft(work, github, None).run()

    assert github.writes == [f"open_draft feature {RepositoriesByOwner.default_branch}"]


def test_a_draft_stacked_on_a_pull_request_targets_its_branch_and_joins_its_stack(
    work: WritePolicy,
) -> None:
    github = DraftsAndStacksInMemory({1: RepositoriesByOwner.default_branch})

    draft(work, github, 1).run()

    assert github.writes == [
        f"open_draft feature {github.name_branch(1)}",
        "create_stack [1, 2]",
    ]


def test_a_draft_onto_a_pull_request_others_build_on_opens_nothing(
    work: WritePolicy,
) -> None:
    default = RepositoriesByOwner.default_branch
    github = DraftsAndStacksInMemory({1: default, 2: default})
    github.existing_stacks.append(Stack(7, default, True, github.build_stack((1, 2))))

    with pytest.raises(StackContinuesAboveError):
        draft(work, github, 1).run()

    assert [write for write in github.writes if write.startswith("open_draft")] == []


@dataclass(frozen=True)
class EndingNamingTheBranch(DescriptionEnding):
    """
    Ends a description with its branch's name and the branch it targets.
    """

    def append_once(self, body: str, branch: str, base: str) -> str:
        return f"{body} | {branch} onto {base}"


def test_a_draft_onto_the_default_branch_ends_its_description(
    work: WritePolicy,
) -> None:
    github = DraftsAndStacksInMemory({})
    ending = EndingNamingTheBranch()

    replace(draft(work, github, None), ending=ending).run()

    assert github.bodies == {
        1: ending.append_once("A body", "feature", RepositoriesByOwner.default_branch)
    }


@dataclass(frozen=True)
class ReplacedPullRequestInMemory(DraftsAndStacksInMemory):
    """
    The stand-in, answering pull request 4 as given.
    """

    replaced: RestPullRequest | None = None
    """
    Pull request 4.
    """

    def pull_request(self, number: int) -> RestPullRequest:
        if number == 4 and self.replaced is not None:
            return self.replaced
        return super().pull_request(number)


def test_a_replaced_pull_request_is_closed_once_its_draft_is_open(
    work: WritePolicy,
) -> None:
    github = DraftsAndStacksInMemory({4: RepositoriesByOwner.default_branch})
    retired = RetiredInMemory()

    replace(draft(work, github, None), replacement=Replacement(4, retired)).run()

    assert github.writes == [f"open_draft feature {RepositoriesByOwner.default_branch}"]
    assert retired.retired == [(4, "Replaced by #5.")]


@pytest.mark.parametrize(
    "replaced",
    [
        replace(pull_request(4, "old"), state=PullRequestState.CLOSED),
        pull_request(4, "old", repository="someone-else/project"),
        pull_request(4, "feature"),
    ],
    ids=["closed", "on another repository", "the work branch's own"],
)
def test_a_pull_request_a_session_may_not_close_is_not_replaced(
    work: WritePolicy, replaced: RestPullRequest
) -> None:
    github = ReplacedPullRequestInMemory({}, replaced=replaced)
    retired = RetiredInMemory()

    with pytest.raises(UnreplaceablePullRequestError):
        replace(draft(work, github, None), replacement=Replacement(4, retired)).run()

    assert (github.writes, retired.retired) == ([], [])


@dataclass(frozen=True)
class StackingRefusedInMemory(DraftsAndStacksInMemory):
    """
    The stand-in, refusing to create a stack.
    """

    def create_stack(self, pull_requests: Sequence[int]) -> Stack:
        raise RuntimeError("GitHub refused the stack")


@dataclass(frozen=True)
class ClosingRefused(PullRequestRetirement):
    """
    Refuses to close any pull request.
    """

    def retire(self, number: int, reason: str) -> None:
        raise RuntimeError("GitHub refused to close it")


def test_a_draft_whose_stacking_fails_is_reported_as_opened(work: WritePolicy) -> None:
    github = StackingRefusedInMemory({1: RepositoriesByOwner.default_branch})

    with pytest.raises(DraftUnfinishedError) as raised:
        draft(work, github, 1).run()

    assert raised.value.number == 2


def test_a_draft_whose_replaced_pull_request_stays_open_is_reported_as_opened(
    work: WritePolicy,
) -> None:
    github = DraftsAndStacksInMemory({4: RepositoriesByOwner.default_branch})

    with pytest.raises(DraftUnfinishedError) as raised:
        replace(
            draft(work, github, None), replacement=Replacement(4, ClosingRefused())
        ).run()

    assert raised.value.number == 5


def test_a_stacked_draft_s_ending_is_given_the_branch_it_is_stacked_on(
    work: WritePolicy,
) -> None:
    github = DraftsAndStacksInMemory({1: RepositoriesByOwner.default_branch})
    ending = EndingNamingTheBranch()

    replace(draft(work, github, 1), ending=ending).run()

    assert github.bodies == {
        2: ending.append_once("A body", "feature", github.name_branch(1))
    }


def test_a_draft_for_a_branch_github_lacks_is_refused(work: WritePolicy) -> None:
    BranchStart(work, BranchName("unpushed")).run()
    github = DraftsAndStacksInMemory({})

    with pytest.raises(BranchNotPushedError):
        draft(work, github, None).run()

    assert github.writes == []


def test_a_checked_out_default_branch_behind_github_s_is_fast_forwarded(
    work: WritePolicy, repositories: RepositoriesByOwner, owned_url: str
) -> None:
    """
    A cloud session often starts on the default branch.
    """
    other = repositories.clone(owned_url, "other").git
    other.run("commit", "--quiet", "--allow-empty", "--message", "Moved on")
    other.run("push", "--quiet", "origin", f"HEAD:{RepositoriesByOwner.default_branch}")
    git = work.checkout.git
    git.run("switch", "--quiet", RepositoriesByOwner.default_branch)
    default = work.remote.branch(RepositoriesByOwner.default_branch)
    default.fetch().raise_if_failed()

    LocalBranchFollowing(work.checkout.working_tree).follow(default)

    assert git.run("rev-parse", "HEAD") == other.run("rev-parse", "HEAD")


# %% syncing


def other_clone_pushing(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
) -> WritePolicy:
    """:return: A second clone, on the work branch, with one more commit pushed."""
    other = build_write_policy(repositories.clone(owned_url, "other"), settings)
    BranchSwitch(other, BranchName("feature")).run()
    CommitWork(other, "Add c", [write(other.checkout, "c.txt")]).run()
    PushWork(other).run()
    return other


def test_a_branch_github_moved_on_is_fast_forwarded(
    work: WritePolicy,
    repositories: RepositoriesByOwner,
    owned_url: str,
    settings: WorkflowSettings,
) -> None:
    other = other_clone_pushing(repositories, owned_url, settings)

    BranchSync(work, PullRequestsFromBranchesInMemory()).run()

    assert work.checkout.git.run("rev-parse", "HEAD") == other.checkout.git.run(
        "rev-parse", "HEAD"
    )


def test_a_branch_github_rebased_is_moved_to_github_s(
    work: WritePolicy,
    repositories: RepositoriesByOwner,
    owned_url: str,
    settings: WorkflowSettings,
) -> None:
    """
    GitHub's *Rebase stack* rewrites the branch; every local commit had been pushed.
    """
    rebaser = repositories.clone(owned_url, "rebaser").git
    rebaser.run("switch", "--quiet", "feature")
    rebaser.run("commit", "--quiet", "--amend", "--message", "Rebased")
    rebaser.run("push", "--quiet", "--force", "origin", "feature")

    BranchSync(work, PullRequestsFromBranchesInMemory()).run()

    assert work.checkout.git.run("rev-parse", "HEAD") == rebaser.run(
        "rev-parse", "HEAD"
    )


def test_a_rebased_branch_already_fetched_is_still_moved_to_github_s(
    work: WritePolicy, repositories: RepositoriesByOwner, owned_url: str
) -> None:
    """
    A plain fetch moved the remote-tracking branch to the rebased commit already; its
    reflog still holds the one pushed.
    """
    rebaser = repositories.clone(owned_url, "rebaser").git
    rebaser.run("switch", "--quiet", "feature")
    rebaser.run("commit", "--quiet", "--amend", "--message", "Rebased")
    rebaser.run("push", "--quiet", "--force", "origin", "feature")
    work.checkout.git.run("fetch", "--quiet", "origin")

    BranchSync(work, PullRequestsFromBranchesInMemory()).run()

    assert work.checkout.git.run("rev-parse", "HEAD") == rebaser.run(
        "rev-parse", "HEAD"
    )


def test_a_branch_with_unpushed_commits_github_diverged_from_is_left_alone(
    work: WritePolicy,
    repositories: RepositoriesByOwner,
    owned_url: str,
    settings: WorkflowSettings,
) -> None:
    other_clone_pushing(repositories, owned_url, settings)
    CommitWork(work, "Add b", [write(work.checkout, "b.txt")]).run()
    before = work.checkout.git.run("rev-parse", "HEAD")

    with pytest.raises(UnpushedCommitsError):
        BranchSync(work, PullRequestsFromBranchesInMemory()).run()

    assert work.checkout.git.run("rev-parse", "HEAD") == before


def test_a_branch_deleted_from_github_is_not_reported_as_never_pushed(
    work: WritePolicy, repositories: RepositoriesByOwner, owned_url: str
) -> None:
    """
    GitHub deletes a branch once its pull request is merged; pushing it again would
    bring it back.
    """
    deleter = repositories.clone(owned_url, "deleter").git
    deleter.run("push", "--quiet", "origin", "--delete", "feature")

    with pytest.raises(BranchDeletedFromGitHubError):
        BranchSync(work, PullRequestsFromBranchesInMemory()).run()


def test_a_branch_the_sandbox_tracks_but_never_pushed_is_not_reported_deleted(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
) -> None:
    """
    A cloud session's sandbox creates the remote-tracking reference of the session's
    branch at setup, without pushing the branch.
    """
    policy = build_write_policy(repositories.clone(owned_url, "sandbox"), settings)
    git = policy.checkout.git
    git.run("switch", "--quiet", "--create", "claude/session-branch")
    git.run("update-ref", "refs/remotes/origin/claude/session-branch", "HEAD")

    BranchSync(policy, PullRequestsFromBranchesInMemory()).run()


def test_a_cloned_branch_deleted_after_its_pull_request_is_reported_deleted(
    work: WritePolicy,
    repositories: RepositoriesByOwner,
    owned_url: str,
    settings: WorkflowSettings,
) -> None:
    """
    A clone writes no reflog entry for the branches it tracks, so the pull request
    opened from the branch shows it was on GitHub.
    """
    session = build_write_policy(repositories.clone(owned_url, "session"), settings)
    session.checkout.git.run("switch", "--quiet", "feature")
    deleter = repositories.clone(owned_url, "deleter").git
    deleter.run("push", "--quiet", "origin", "--delete", "feature")

    with pytest.raises(BranchDeletedFromGitHubError):
        BranchSync(
            session, PullRequestsFromBranchesInMemory([pull_request(1, "feature")])
        ).run()


def cut_off_from_github(policy: WritePolicy, repositories: RepositoriesByOwner) -> None:
    """
    :param policy: The rules of a clone, whose remote then points where no repository
        is.
    :param repositories: The scratch repositories.
    """
    unreachable = (
        repositories.root / "unreachable" / f"{repositories.repository_name}.git"
    )
    policy.checkout.git.run(
        "remote", "set-url", policy.remote.name, f"file://{unreachable}"
    )


def test_a_pushed_branch_is_not_reported_deleted_when_github_cannot_be_reached(
    work: WritePolicy, repositories: RepositoriesByOwner
) -> None:
    cut_off_from_github(work, repositories)

    with pytest.raises(GitCommandFailed):
        BranchSync(work, PullRequestsFromBranchesInMemory()).run()


def test_a_branch_is_not_reported_unpushed_when_github_cannot_be_reached(
    work: WritePolicy, repositories: RepositoriesByOwner
) -> None:
    BranchStart(work, BranchName("unpushed")).run()
    cut_off_from_github(work, repositories)

    with pytest.raises(GitCommandFailed):
        BranchSync(work, PullRequestsFromBranchesInMemory()).run()


# %% taking in the default branch


@dataclass(frozen=True)
class PullRequestsFromBranchesInMemory(PullRequestsFromForks):
    """
    The pull requests opened from each branch, as given.
    """

    opened: list[RestPullRequest] = field(default_factory=list)
    """
    Every pull request.
    """

    def fork_branch_pull_requests(
        self, owner: str, branch: BranchName
    ) -> list[RestPullRequest]:
        return [
            pull_request
            for pull_request in self.opened
            if pull_request.head.branch == branch
        ]

    def open_fork_pull_request(
        self, owner: str, branch: BranchName, base: BranchName, title: str, body: str
    ) -> RestPullRequest:
        raise NotImplementedError


@dataclass(frozen=True)
class BranchStacksInMemory(
    PullRequestsFromBranchesInMemory, StackedPullRequestsInMemory, BranchStacks
):
    """
    The pull requests opened from each branch, as given, and the stacks holding them.
    """


def advance_default_branch(
    repositories: RepositoriesByOwner, owned_url: str, name: str = "moved.txt"
) -> GitCommandRunner:
    """
    :param repositories: The scratch repositories.
    :param owned_url: The owner's repository.
    :param name: The file the new commit on the default branch writes.
    :return: The clone that pushed it.
    """
    other = repositories.clone(owned_url, "other").git
    (other.working_directory / name).write_text("moved on\n")
    other.run("add", name)
    other.run("commit", "--quiet", "--message", "Move on")
    other.run("push", "--quiet", "origin", f"HEAD:{RepositoriesByOwner.default_branch}")
    return other


def base_merge(
    work: WritePolicy, opened: list[RestPullRequest] | None = None
) -> BaseMerge:
    """
    :param work: The rules of a clone on a pushed work branch.
    :param opened: The pull requests opened from its branches.
    :return: The merge of the default branch into the work branch.
    """
    return BaseMerge(work, BranchStacksInMemory({}, opened=opened or []))


def test_the_default_branch_s_new_commits_are_merged_into_the_work_branch(
    work: WritePolicy, repositories: RepositoriesByOwner, owned_url: str
) -> None:
    other = advance_default_branch(repositories, owned_url)

    base_merge(work).run()

    git = work.checkout.git
    assert RepositoriesByOwner.is_ancestor(
        git, other.run("rev-parse", "HEAD"), git.run("rev-parse", "HEAD")
    )
    assert Attribution.ACKNOWLEDGEMENT in last_message(git)


def test_a_conflicting_merge_is_left_in_progress_naming_its_files(
    work: WritePolicy, repositories: RepositoriesByOwner, owned_url: str
) -> None:
    advance_default_branch(repositories, owned_url, "a.txt")
    git = work.checkout.git

    with pytest.raises(MergeConflictError) as raised:
        base_merge(work).run()

    assert raised.value.files == ("a.txt",)
    assert Merge(WorkingTree(git)).in_progress()


# %% finishing or undoing a conflicting merge


def leave_conflicting_merge(
    work: WritePolicy, repositories: RepositoriesByOwner, owned_url: str
) -> GitCommandRunner:
    """
    Leave a merge of the default branch into the work branch in progress, conflicting in
    ``a.txt``.

    :param work: The rules of a clone on a pushed work branch with ``a.txt``.
    :param repositories: The scratch repositories.
    :param owned_url: The owner's repository.
    :return: The clone that moved the default branch on.
    """
    other = advance_default_branch(repositories, owned_url, "a.txt")
    with pytest.raises(MergeConflictError):
        base_merge(work).run()
    return other


def test_a_resolved_merge_is_committed_as_the_person(
    work: WritePolicy, repositories: RepositoriesByOwner, owned_url: str
) -> None:
    other = leave_conflicting_merge(work, repositories, owned_url)
    (work.checkout.root / "a.txt").write_text("both sides\n")

    MergeCompletion(work, [Path("a.txt")]).run()

    git = work.checkout.git
    parents = git.run("log", "--max-count=1", "--format=%P").split()
    assert (
        len(parents),
        RepositoriesByOwner.is_ancestor(git, other.run("rev-parse", "HEAD"), "HEAD"),
    ) == (
        2,
        True,
    )
    assert Attribution.ACKNOWLEDGEMENT in last_message(git)
    assert not Merge(WorkingTree(git)).in_progress()


def test_a_conflict_resolved_by_deleting_the_file_is_committed(
    work: WritePolicy, repositories: RepositoriesByOwner, owned_url: str
) -> None:
    leave_conflicting_merge(work, repositories, owned_url)
    (work.checkout.root / "a.txt").unlink()

    MergeCompletion(work, [Path("a.txt")]).run()

    git = work.checkout.git
    assert (Merge(WorkingTree(git)).in_progress(), git.run("ls-files", "a.txt")) == (
        False,
        "",
    )


def test_a_conflict_resolved_to_binary_content_is_committed(
    work: WritePolicy, repositories: RepositoriesByOwner, owned_url: str
) -> None:
    leave_conflicting_merge(work, repositories, owned_url)
    (work.checkout.root / "a.txt").write_bytes(bytes([0xFF, 0xFE, 0x00, 0x80]))

    MergeCompletion(work, [Path("a.txt")]).run()

    assert not Merge(WorkingTree(work.checkout.git)).in_progress()


def test_a_file_still_marking_a_conflict_is_refused(
    work: WritePolicy, repositories: RepositoriesByOwner, owned_url: str
) -> None:
    leave_conflicting_merge(work, repositories, owned_url)

    with pytest.raises(ConflictMarkersLeftError):
        MergeCompletion(work, [Path("a.txt")]).run()

    assert work.checkout.merge.in_progress()


def test_a_conflicting_file_left_out_is_refused(
    work: WritePolicy, repositories: RepositoriesByOwner, owned_url: str
) -> None:
    leave_conflicting_merge(work, repositories, owned_url)
    (work.checkout.root / "b.txt").write_text("unrelated\n")

    with pytest.raises(UnresolvedConflictError):
        MergeCompletion(work, [Path("b.txt")]).run()

    assert work.checkout.merge.in_progress()


def test_an_undone_merge_leaves_the_branch_as_it_was(
    work: WritePolicy, repositories: RepositoriesByOwner, owned_url: str
) -> None:
    git = work.checkout.git
    before = git.run("rev-parse", "HEAD")
    leave_conflicting_merge(work, repositories, owned_url)

    MergeAbort(work).run()

    assert (git.run("rev-parse", "HEAD"), git.run("status", "--porcelain")) == (
        before,
        "",
    )


def test_no_merge_in_progress_has_nothing_to_finish(work: WritePolicy) -> None:
    with pytest.raises(NoMergeInProgressError):
        MergeCompletion(work, [Path("a.txt")]).run()


def test_no_merge_in_progress_has_nothing_to_undo(work: WritePolicy) -> None:
    with pytest.raises(NoMergeInProgressError):
        MergeAbort(work).run()


def test_a_branch_mid_merge_is_neither_committed_to_nor_pushed(
    work: WritePolicy, repositories: RepositoriesByOwner, owned_url: str
) -> None:
    leave_conflicting_merge(work, repositories, owned_url)
    path = write(work.checkout, "c.txt")

    with pytest.raises(MergeInProgressError):
        CommitWork(work, "More", [path]).run()
    with pytest.raises(MergeInProgressError):
        PushWork(work).run()


def test_a_branch_higher_in_a_stack_does_not_take_in_the_default_branch(
    work: WritePolicy, repositories: RepositoriesByOwner, owned_url: str
) -> None:
    """
    It targets the branch below it, not the default branch.
    """
    advance_default_branch(repositories, owned_url)
    above = pull_request(4, "feature", base=StackedPullRequestsInMemory.name_branch(3))
    branches = BranchStacksInMemory({}, opened=[above])
    branches.existing_stacks.append(
        Stack(1, "main", True, branches.build_stack([3, 4]))
    )
    git = work.checkout.git
    before = git.run("rev-parse", "HEAD")

    with pytest.raises(StackedBranchMergeError):
        BaseMerge(work, branches).run()

    assert git.run("rev-parse", "HEAD") == before


def test_the_bottom_of_a_stack_takes_in_the_default_branch(
    work: WritePolicy, repositories: RepositoriesByOwner, owned_url: str
) -> None:
    other = advance_default_branch(repositories, owned_url)
    branches = BranchStacksInMemory({}, opened=[pull_request(3, "feature")])
    branches.existing_stacks.append(
        Stack(1, "main", True, branches.build_stack([3, 4]))
    )

    BaseMerge(work, branches).run()

    git = work.checkout.git
    assert RepositoriesByOwner.is_ancestor(
        git, other.run("rev-parse", "HEAD"), git.run("rev-parse", "HEAD")
    )


def test_the_default_branch_takes_in_nothing(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
) -> None:
    policy = build_write_policy(repositories.clone(owned_url, "on-default"), settings)

    with pytest.raises(DefaultBranchWriteError):
        base_merge(policy).run()


def test_a_branch_that_has_the_default_branch_s_commits_is_left_alone(
    work: WritePolicy,
) -> None:
    git = work.checkout.git
    before = git.run("rev-parse", "HEAD")

    base_merge(work).run()

    assert git.run("rev-parse", "HEAD") == before


# %% building on another pull request


@dataclass(frozen=True)
class PullRequestsByNumber(PullRequestReader):
    """
    Answers each pull request asked for from the ones given.
    """

    pull_requests: dict[int, RestPullRequest]
    """
    The pull requests, by number.
    """

    def pull_request(self, number: int) -> RestPullRequest:
        return self.pull_requests[number]

    def open_pull_requests(self) -> list[RestPullRequest]:
        raise NotImplementedError


def pushed_below(
    work: WritePolicy,
    repositories: RepositoriesByOwner,
    owned_url: str,
    state: PullRequestState = PullRequestState.OPEN,
    repository: str | None = None,
) -> tuple[PullRequestMerge, GitCommandRunner]:
    """
    Push a branch ``below`` with a commit of its own, as another session's pull request
    56 would.

    :param work: The rules of a clone on a pushed work branch.
    :param repositories: The scratch repositories.
    :param owned_url: The owner's repository.
    :param state: Whether pull request 56 is open.
    :param repository: The repository its branch is on, the owner's when ``None``.
    :return: The merge of its branch into the work branch, and the clone that pushed it.
    """
    other = repositories.clone(owned_url, "other").git
    other.run("switch", "--quiet", "--create", "below")
    (other.working_directory / "below.txt").write_text("below\n")
    other.run("add", "below.txt")
    other.run("commit", "--quiet", "--message", "Make the tests load")
    other.run("push", "--quiet", "origin", "below")
    on = work.remote.repository.full_name if repository is None else repository
    below = pull_request(56, "below", state=state, repository=on)
    return PullRequestMerge(work, PullRequestsByNumber({56: below}), 56), other


def test_another_pull_request_s_branch_is_merged_into_the_work_branch(
    work: WritePolicy, repositories: RepositoriesByOwner, owned_url: str
) -> None:
    merge, other = pushed_below(work, repositories, owned_url)

    merge.run()

    git = work.checkout.git
    assert RepositoriesByOwner.is_ancestor(
        git, other.run("rev-parse", "HEAD"), git.run("rev-parse", "HEAD")
    )
    assert Attribution.ACKNOWLEDGEMENT in last_message(git)


@pytest.mark.parametrize(
    "state, repository",
    [(PullRequestState.CLOSED, None), (PullRequestState.OPEN, "someone-else/project")],
    ids=["closed", "on another repository"],
)
def test_a_pull_request_that_cannot_be_built_on_is_refused(
    work: WritePolicy,
    repositories: RepositoriesByOwner,
    owned_url: str,
    state: PullRequestState,
    repository: str | None,
) -> None:
    merge, _ = pushed_below(work, repositories, owned_url, state, repository)
    git = work.checkout.git
    before = git.run("rev-parse", "HEAD")

    with pytest.raises(UnbuildablePullRequestError):
        merge.run()

    assert git.run("rev-parse", "HEAD") == before


def test_the_default_branch_builds_on_no_pull_request(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
) -> None:
    policy = build_write_policy(repositories.clone(owned_url, "on-default"), settings)
    below = pull_request(56, "below", repository=policy.remote.repository.full_name)

    with pytest.raises(DefaultBranchWriteError):
        PullRequestMerge(policy, PullRequestsByNumber({56: below}), 56).run()


# %% rewriting a pull request's description and title


def rewrite(
    github: DraftsInMemory, body: str | None, title: str | None = None
) -> DescriptionRewrite:
    """
    :param github: The pull requests.
    :param body: The new description, ``None`` to keep it.
    :param title: The new title, ``None`` to keep it.
    :return: The rewrite of pull request 1.
    """
    return DescriptionRewrite(github, 1, body, title, repository=ScratchGitHub.owned)


@dataclass(frozen=True)
class DraftsFromAnotherFork(DraftsInMemory):
    """
    The stand-in, every pull request opened from a branch of somebody else's fork.
    """

    def pull_request(self, number: int) -> RestPullRequest:
        opened = super().pull_request(number)
        foreign = f"{RepositoriesByOwner.foreign_owner}/project"
        return replace(opened, head=replace(opened.head, repository=foreign))


def test_a_pull_request_from_somebody_else_s_fork_is_not_rewritten() -> None:
    github = DraftsFromAnotherFork({1: RepositoriesByOwner.default_branch})

    with pytest.raises(ForeignPullRequestError):
        rewrite(github, "A new body").run()

    assert github.writes == []


@pytest.mark.parametrize(
    "drafts", [frozenset({1}), frozenset()], ids=["draft", "ready for review"]
)
def test_an_open_pull_request_s_description_is_rewritten(
    drafts: frozenset[int],
) -> None:
    """
    Its description follows the pushed commits, ready for review or not.
    """
    github = DraftsInMemory({1: RepositoriesByOwner.default_branch}, drafts=drafts)
    step = rewrite(github, "A new body")

    step.run()

    assert github.writes == ["set_description 1 A new body"]


def test_a_new_description_onto_the_default_branch_ends_as_a_draft_s_does() -> None:
    github = DraftsInMemory({1: RepositoriesByOwner.default_branch})
    step = rewrite(github, "A new body")
    ending = EndingNamingTheBranch()

    replace(step, ending=ending).run()

    described = ending.append_once(
        "A new body", github.name_branch(1), RepositoriesByOwner.default_branch
    )
    assert github.writes == [f"set_description 1 {described}"]


def test_a_new_description_s_ending_is_given_the_branch_it_targets() -> None:
    github = DraftsInMemory({1: RepositoriesByOwner.default_branch, 2: "branch-1"})
    step = rewrite(github, "A new body")
    ending = EndingNamingTheBranch()

    replace(step, number=2, ending=ending).run()

    described = ending.append_once("A new body", github.name_branch(2), "branch-1")
    assert github.writes == [f"set_description 2 {described}"]


def test_a_new_description_keeps_the_old_one_s_closing_lines() -> None:
    closing = ClosingKeyword.FIXES.reference(148)
    old = f"What it did.\n\n{closing}\n"

    kept = ClosingLines(old).append_missing_lines("What it does now.\n")

    assert kept == f"What it does now.\n\n{closing}\n"


def test_a_closing_line_the_new_description_has_is_not_repeated() -> None:
    closing = ClosingKeyword.FIXES.reference(148)
    rewritten = f"What it does now.\n\n{closing}\n"

    assert (
        ClosingLines(f"What it did.\n\n{closing}\n").append_missing_lines(rewritten)
        == rewritten
    )


def test_an_open_pull_request_s_title_is_rewritten() -> None:
    github = DraftsInMemory({1: RepositoriesByOwner.default_branch})
    step = rewrite(github, None, "A sharper title")

    step.run()

    assert github.writes == ["set_issue_title 1 A sharper title"]


def test_a_closed_pull_request_keeps_its_description_and_title() -> None:
    github = DraftsInMemory(
        {1: RepositoriesByOwner.default_branch}, closed=frozenset({1})
    )
    step = rewrite(github, "A new body", "A sharper title")

    with pytest.raises(PullRequestNotOpenError):
        step.run()

    assert github.writes == []


def test_a_rewrite_changing_nothing_is_refused() -> None:
    github = DraftsInMemory({1: RepositoriesByOwner.default_branch})
    step = rewrite(github, None)

    with pytest.raises(NothingToDescribeError):
        step.run()

    assert github.writes == []


# %% commenting on a pull request


def test_a_comment_is_posted_on_the_pull_request_named() -> None:
    github = DraftsInMemory({1: "main"})

    PullRequestComment(github, 1, "The plan.").run()

    assert github.writes == ["add_comment 1"]


def test_a_closed_pull_request_is_commented_on_too() -> None:
    github = DraftsInMemory({1: "main"}, closed=frozenset({1}))

    PullRequestComment(github, 1, "A correction.").run()

    assert github.writes == ["add_comment 1"]


def test_commenting_on_a_pull_request_is_the_person_s_word() -> None:
    words = list(RunnableCommand.COMMENT.words)

    assert not RunnableCommand.COMMENT.runs_unasked(words)


# %% reviewing a pull request


@dataclass(frozen=True)
class ReviewsInMemory(Reviewer):
    """
    The stand-in keeping the reviews submitted.
    """

    submitted: list[tuple[int, str]] = field(default_factory=list)
    """
    Each review submitted: the pull request and the review's text.
    """

    @classproperty
    def review_page(cls) -> str:
        """
        The URL every submitted review is given.
        """
        return "https://github.com/an-owner/a-repository/pull/1#pullrequestreview-1"

    def submit_review(self, number: int, body: str) -> str:
        self.submitted.append((number, body))
        return self.review_page


def test_a_review_is_submitted_on_the_pull_request_named() -> None:
    github = ReviewsInMemory()

    PullRequestReview(github, 1, "Reads well.").run()

    assert github.submitted == [(1, "Reads well.")]


def test_a_submitted_review_is_reported_with_its_page() -> None:
    reported = PullRequestReview(ReviewsInMemory(), 1, "Reads well.").run()

    assert reported == f"reviewed #1: {ReviewsInMemory.review_page}"


def test_reviewing_a_pull_request_is_the_person_s_word() -> None:
    words = list(RunnableCommand.REVIEW_SUBMIT.words)

    assert not RunnableCommand.REVIEW_SUBMIT.runs_unasked(words)


# %% cloning


def test_a_repository_of_the_owner_s_is_cloned_into_the_directory(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
) -> None:
    repository = Repository(settings.owner, RepositoriesByOwner.repository_name)
    directory = repositories.root / "session"

    RepositoryCloning(
        repository, directory, settings, f"file://{repositories.root}"
    ).run()

    [published] = repositories.branches(owned_url).splitlines()
    clone = GitCommandRunner(directory / repository.name)
    assert clone.run("rev-parse", "HEAD") == published.split()[0]


def test_somebody_else_s_repository_is_cloned_to_be_read(
    repositories: RepositoriesByOwner, foreign_url: str, settings: WorkflowSettings
) -> None:
    repository = Repository(
        RepositoriesByOwner.foreign_owner, RepositoriesByOwner.repository_name
    )
    directory = repositories.root / "session"

    RepositoryCloning(
        repository, directory, settings, f"file://{repositories.root}"
    ).run()

    [published] = repositories.branches(foreign_url).splitlines()
    clone = GitCommandRunner(directory / repository.name)
    assert clone.run("rev-parse", "HEAD") == published.split()[0]


def test_a_clone_carries_the_workflow_s_push_hook(
    repositories: RepositoriesByOwner, foreign_url: str, settings: WorkflowSettings
) -> None:
    repository = Repository(
        RepositoriesByOwner.foreign_owner, RepositoriesByOwner.repository_name
    )
    directory = repositories.root / "session"

    RepositoryCloning(
        repository, directory, settings, f"file://{repositories.root}"
    ).run()

    clone = ProjectCheckout(GitCommandRunner(directory / repository.name))
    hook = PushHook(clone, Path(sys.executable))
    assert hook.path.read_text() == hook.script


def test_a_session_s_push_from_a_clone_of_somebody_else_s_repository_is_refused(
    repositories: RepositoriesByOwner,
    foreign_url: str,
    settings: WorkflowSettings,
    in_claude_code: None,
) -> None:
    """
    A push run outside the workflow's commands, by a script, still meets the hook.
    """
    repository = Repository(
        RepositoriesByOwner.foreign_owner, RepositoriesByOwner.repository_name
    )
    directory = repositories.root / "session"
    RepositoryCloning(
        repository, directory, settings, f"file://{repositories.root}"
    ).run()
    clone = GitCommandRunner(directory / repository.name)
    before = repositories.branches(foreign_url)

    pushed = clone.attempt("push", "origin", "HEAD:refs/heads/work")

    assert not pushed.succeeded
    assert repositories.branches(foreign_url) == before


def test_a_clone_from_inside_a_checkout_goes_next_to_it(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
) -> None:
    checkout = repositories.clone(owned_url, "mine")
    repository = Repository(settings.owner, "another")
    arguments = RunnableCommand.parser().parse_args(
        [WorkflowCommand.CLONE, repository.full_name]
    )

    step = WorkflowSession(checkout.root, settings).step(arguments)

    assert step == RepositoryCloning(repository, checkout.root.parent, settings)


def test_somebody_else_s_repository_is_cloned_into_the_plugin_s_data(
    repositories: RepositoriesByOwner,
    owned_url: str,
    settings: WorkflowSettings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = tmp_path / "plugin-data"
    monkeypatch.setenv(WorkflowVariable.PLUGIN_DATA, str(data))
    checkout = repositories.clone(owned_url, RepositoriesByOwner.repository_name)
    upstream = Repository(
        RepositoriesByOwner.foreign_owner, RepositoriesByOwner.repository_name
    )
    arguments = RunnableCommand.parser().parse_args(
        [WorkflowCommand.CLONE, upstream.full_name]
    )

    step = WorkflowSession(checkout.root, settings).step(arguments)

    assert step == RepositoryCloning(
        upstream, data / PluginDataDirectory.CLONES / upstream.owner, settings
    )


def test_somebody_else_s_repository_is_not_cloned_without_the_plugin_s_data(
    repositories: RepositoriesByOwner,
    owned_url: str,
    settings: WorkflowSettings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(WorkflowVariable.PLUGIN_DATA, raising=False)
    checkout = repositories.clone(owned_url, RepositoriesByOwner.repository_name)
    upstream = Repository(
        RepositoriesByOwner.foreign_owner, RepositoriesByOwner.repository_name
    )
    arguments = RunnableCommand.parser().parse_args(
        [WorkflowCommand.CLONE, upstream.full_name]
    )

    with pytest.raises(UnknownPluginDataError):
        WorkflowSession(checkout.root, settings).step(arguments)


def test_a_repository_cloned_before_is_reused(
    repositories: RepositoriesByOwner, foreign_url: str, settings: WorkflowSettings
) -> None:
    repository = Repository(
        RepositoriesByOwner.foreign_owner, RepositoriesByOwner.repository_name
    )
    cloning = RepositoryCloning(
        repository,
        repositories.root / "session",
        settings,
        f"file://{repositories.root}",
    )
    cloning.run()
    clone = GitCommandRunner(cloning.directory / repository.name)
    clone.run("commit", "--quiet", "--allow-empty", "--message", "Read along")
    reviewed = clone.run("rev-parse", "HEAD")

    cloning.run()

    assert clone.run("rev-parse", "HEAD") == reviewed


def test_a_clone_from_outside_a_checkout_goes_into_the_directory(
    tmp_path: Path, settings: WorkflowSettings
) -> None:
    repository = Repository(settings.owner, "another")
    arguments = RunnableCommand.parser().parse_args(
        [WorkflowCommand.CLONE, repository.full_name]
    )

    step = WorkflowSession(tmp_path, settings).step(arguments)

    assert step == RepositoryCloning(repository, tmp_path, settings)
