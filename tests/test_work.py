"""
Tests for :mod:`github_workflow.work`: every write a session makes, and every write the
policy refuses before it is attempted.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

import github_workflow
from basstler_domain_model.environment import GitIdentityVariable
from basstler_domain_model.git.commands import GitCommandRunner, RemoteBranch
from basstler_domain_model.git.exceptions import GitCommandFailed
from basstler_domain_model.github.repository_client import RepositoryDetails
from basstler_domain_model.repository import Repository

from github_workflow.__main__ import WorkflowSession
from github_workflow.checkout import ProjectCheckout
from github_workflow.command_line import WorkflowCommand
from github_workflow.exceptions import (
    AssistantCreditError,
    BranchDeletedFromGitHubError,
    BranchNotPushedError,
    DefaultBranchWriteError,
    DetachedHeadError,
    NotADraftError,
    PushRefusedError,
    UnpushedCommitsError,
)
from github_workflow.policy import Attribution, WritePolicy
from github_workflow.push_hook import PushHook
from github_workflow.remotes import OwnedRemotes
from github_workflow.settings import WorkflowSettings
from github_workflow.stacks import StackPlacement
from github_workflow.work import (
    BranchStart,
    BranchSwitch,
    BranchSync,
    CommitWork,
    DescriptionRewrite,
    DraftOpening,
    PullRequestBranches,
    PushWork,
    RepositoryCloning,
)

from .repositories_by_owner import RepositoriesByOwner
from .test_push_hook import in_claude_code  # noqa: F401  (a fixture)
from .stacked_pull_requests import DraftsAndStacksInMemory, DraftsInMemory

# %% helpers


@dataclass(frozen=True)
class PullRequestBranchesInMemory(PullRequestBranches):
    """
    The branches pull requests were opened from, as a set.
    """

    branches: frozenset[str] = frozenset()
    """
    Each branch a pull request was opened from.
    """

    def opened_from(self, branch: str) -> bool:
        return branch in self.branches


class DefaultBranchOfTheScratchRepositories(RepositoryDetails):
    """
    Answers the default branch every scratch repository starts with.
    """

    def default_branch(self) -> str:
        return RepositoriesByOwner.default_branch


def policy_in(checkout: ProjectCheckout, settings: WorkflowSettings) -> WritePolicy:
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
    policy = policy_in(repositories.clone(owned_url, "work"), settings)
    BranchStart(policy, "feature").run()
    CommitWork(policy, "Add a file", [write(policy.checkout, "a.txt")]).run()
    PushWork(policy).run()
    return policy


# %% branches


def test_a_work_branch_starts_from_github_s_default_branch(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
):
    policy = policy_in(repositories.clone(owned_url, "work"), settings)

    BranchStart(policy, "feature").run()

    git = policy.checkout.git
    assert git.checked_out_branch() == "feature"
    assert git.commit_at("HEAD") == git.commit_at(
        RemoteBranch(policy.remote.name, policy.default_branch).tracking_reference
    )


def test_a_work_branch_starts_on_another_branch_when_asked(work: WritePolicy):
    git = work.checkout.git

    BranchStart(work, "upper", "feature").run()

    assert git.commit_at("upper") == git.commit_at("feature")


def test_a_work_branch_starts_on_a_local_branch_github_does_not_have(
    work: WritePolicy,
):
    git = work.checkout.git
    BranchStart(work, "unpushed").run()
    CommitWork(work, "Add b", [write(work.checkout, "b.txt")]).run()

    BranchStart(work, "upper", "unpushed").run()

    assert git.commit_at("upper") == git.commit_at("unpushed")


def github_s_default_branch_moved_on(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
) -> str:
    """:return: The commit GitHub's default branch moved on to, pushed from a second
    clone."""
    mover = policy_in(repositories.clone(owned_url, "mover"), settings)
    git = mover.checkout.git
    write(mover.checkout, "moved.txt")
    git.run("add", "moved.txt")
    git.run("commit", "--quiet", "--message", "Move on")
    default = RemoteBranch(mover.remote.name, RepositoriesByOwner.default_branch)
    git.run("push", "--quiet", default.remote, f"HEAD:{default.reference}")
    return git.commit_at("HEAD")


def test_starting_from_the_default_branch_fast_forwards_the_local_one(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
):
    policy = policy_in(repositories.clone(owned_url, "work"), settings)
    moved = github_s_default_branch_moved_on(repositories, owned_url, settings)

    BranchStart(policy, "feature").run()

    assert policy.checkout.git.commit_at(policy.default_branch) == moved


def test_a_local_default_branch_with_commits_of_its_own_is_kept(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
):
    policy = policy_in(repositories.clone(owned_url, "work"), settings)
    git = policy.checkout.git
    write(policy.checkout, "own.txt")
    git.run("add", "own.txt")
    git.run("commit", "--quiet", "--message", "Own")
    own = git.commit_at("HEAD")
    github_s_default_branch_moved_on(repositories, owned_url, settings)

    BranchStart(policy, "feature").run()

    assert git.commit_at(policy.default_branch) == own


def test_starting_from_another_branch_leaves_the_local_default_branch_alone(
    work: WritePolicy,
    repositories: RepositoriesByOwner,
    owned_url: str,
    settings: WorkflowSettings,
):
    git = work.checkout.git
    before = git.commit_at(work.default_branch)
    github_s_default_branch_moved_on(repositories, owned_url, settings)

    BranchStart(work, "upper", "feature").run()

    assert git.commit_at(work.default_branch) == before


def test_switching_checks_out_the_branch(work: WritePolicy):
    BranchSwitch(work, RepositoriesByOwner.default_branch).run()

    assert work.checkout.git.checked_out_branch() == RepositoriesByOwner.default_branch


# %% committing


def test_a_commit_acknowledges_the_assistant_s_help(work: WritePolicy):
    CommitWork(work, "Add b", [write(work.checkout, "b.txt")]).run()

    assert last_message(work.checkout.git) == f"Add b\n\n{Attribution.ACKNOWLEDGEMENT}"


def test_a_commit_already_acknowledging_it_is_left_as_it_is(work: WritePolicy):
    message = f"Add b\n\n{Attribution.ACKNOWLEDGEMENT}"

    CommitWork(work, message, [write(work.checkout, "b.txt")]).run()

    assert last_message(work.checkout.git) == message


def test_a_commit_crediting_an_assistant_as_co_author_is_refused(work: WritePolicy):
    message = "Add b\n\nCo-Authored-By: Claude <noreply@anthropic.com>"
    before = work.checkout.git.commit_at("HEAD")

    with pytest.raises(AssistantCreditError):
        CommitWork(work, message, [write(work.checkout, "b.txt")]).run()

    assert work.checkout.git.commit_at("HEAD") == before


def test_a_commit_authored_as_an_assistant_is_refused(work: WritePolicy):
    work.checkout.git.run("config", "user.email", "noreply@anthropic.com")

    with pytest.raises(AssistantCreditError):
        CommitWork(work, "Add b", [write(work.checkout, "b.txt")]).run()


def test_a_commit_committed_as_an_assistant_is_refused(
    work: WritePolicy, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv(GitIdentityVariable.COMMITTER_EMAIL, "noreply@anthropic.com")
    before = work.checkout.git.commit_at("HEAD")

    with pytest.raises(AssistantCreditError):
        CommitWork(work, "Add b", [write(work.checkout, "b.txt")]).run()

    assert work.checkout.git.commit_at("HEAD") == before


def test_a_person_named_like_the_assistant_may_commit(work: WritePolicy):
    work.checkout.git.run("config", "user.name", "Claude Monet")
    work.checkout.git.run("config", "user.email", "claude.monet@example.com")

    CommitWork(work, "Add b", [write(work.checkout, "b.txt")]).run()

    assert work.checkout.git.run("log", "-1", "--format=%an") == "Claude Monet"


def test_a_commit_needs_no_access_to_github(work: WritePolicy, tmp_path: Path):
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


def test_a_commit_on_the_default_branch_is_refused(work: WritePolicy):
    BranchSwitch(work, RepositoriesByOwner.default_branch).run()

    with pytest.raises(DefaultBranchWriteError):
        CommitWork(work, "Add b", [write(work.checkout, "b.txt")]).run()


def test_a_commit_without_a_branch_is_refused(work: WritePolicy):
    work.checkout.git.run("switch", "--quiet", "--detach")

    with pytest.raises(DetachedHeadError):
        CommitWork(work, "Add b", [write(work.checkout, "b.txt")]).run()


# %% pushing


def test_a_pushed_branch_is_on_the_owner_s_repository(work: WritePolicy):
    branch = RemoteBranch(work.remote.name, "feature")

    assert work.checkout.git.has_remote_branch(branch)


def test_a_pushed_branch_tracks_its_copy_on_the_owner_s_repository(
    work: WritePolicy,
):
    tracked = work.checkout.git.run("rev-parse", "--abbrev-ref", "feature@{upstream}")

    assert tracked == f"{work.remote.name}/feature"


def test_pushing_the_default_branch_is_refused(work: WritePolicy):
    BranchSwitch(work, RepositoriesByOwner.default_branch).run()

    with pytest.raises(DefaultBranchWriteError):
        PushWork(work).run()


def test_a_push_github_would_have_to_be_forced_to_take_is_refused(
    work: WritePolicy,
    repositories: RepositoriesByOwner,
    owned_url: str,
    settings: WorkflowSettings,
):
    other_clone_pushing(repositories, owned_url, settings)
    CommitWork(work, "Add b", [write(work.checkout, "b.txt")]).run()

    with pytest.raises(PushRefusedError):
        PushWork(work).run()


def test_a_push_from_somebody_else_s_repository_is_refused_before_it_is_tried(
    repositories: RepositoriesByOwner, foreign_url: str
):
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
        StackPlacement(github, github, github, github),
        "A title",
        "A body",
        below,
    )


def test_a_draft_targets_the_default_branch(work: WritePolicy):
    github = DraftsAndStacksInMemory({})

    draft(work, github, None).run()

    assert github.writes == [f"open_draft feature {RepositoriesByOwner.default_branch}"]


def test_a_draft_stacked_on_a_pull_request_targets_its_branch_and_joins_its_stack(
    work: WritePolicy,
):
    github = DraftsAndStacksInMemory({1: RepositoriesByOwner.default_branch})

    draft(work, github, 1).run()

    assert github.writes == [
        f"open_draft feature {github.branch_of(1)}",
        "create_stack [1, 2]",
    ]


def test_a_draft_for_a_branch_github_lacks_is_refused(work: WritePolicy):
    BranchStart(work, "unpushed").run()
    github = DraftsAndStacksInMemory({})

    with pytest.raises(BranchNotPushedError):
        draft(work, github, None).run()

    assert github.writes == []


# %% syncing


def other_clone_pushing(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
) -> WritePolicy:
    """:return: A second clone, on the work branch, with one more commit pushed."""
    other = policy_in(repositories.clone(owned_url, "other"), settings)
    BranchSwitch(other, "feature").run()
    CommitWork(other, "Add c", [write(other.checkout, "c.txt")]).run()
    PushWork(other).run()
    return other


def test_a_branch_github_moved_on_is_fast_forwarded(
    work: WritePolicy,
    repositories: RepositoriesByOwner,
    owned_url: str,
    settings: WorkflowSettings,
):
    other = other_clone_pushing(repositories, owned_url, settings)

    BranchSync(work, PullRequestBranchesInMemory()).run()

    assert work.checkout.git.commit_at("HEAD") == other.checkout.git.commit_at("HEAD")


def test_a_branch_github_rebased_is_moved_to_github_s(
    work: WritePolicy,
    repositories: RepositoriesByOwner,
    owned_url: str,
    settings: WorkflowSettings,
):
    """
    GitHub's *Rebase stack* rewrites the branch; every local commit had been pushed.
    """
    rebaser = repositories.clone(owned_url, "rebaser").git
    rebaser.run("switch", "--quiet", "feature")
    rebaser.run("commit", "--quiet", "--amend", "--message", "Rebased")
    rebaser.run("push", "--quiet", "--force", "origin", "feature")

    BranchSync(work, PullRequestBranchesInMemory()).run()

    assert work.checkout.git.commit_at("HEAD") == rebaser.commit_at("HEAD")


def test_a_branch_with_unpushed_commits_github_diverged_from_is_left_alone(
    work: WritePolicy,
    repositories: RepositoriesByOwner,
    owned_url: str,
    settings: WorkflowSettings,
):
    other_clone_pushing(repositories, owned_url, settings)
    CommitWork(work, "Add b", [write(work.checkout, "b.txt")]).run()
    before = work.checkout.git.commit_at("HEAD")

    with pytest.raises(UnpushedCommitsError):
        BranchSync(work, PullRequestBranchesInMemory()).run()

    assert work.checkout.git.commit_at("HEAD") == before


def test_a_branch_deleted_from_github_is_not_reported_as_never_pushed(
    work: WritePolicy, repositories: RepositoriesByOwner, owned_url: str
):
    """
    GitHub deletes a branch once its pull request is merged; pushing it again would
    bring it back.
    """
    deleter = repositories.clone(owned_url, "deleter").git
    deleter.run("push", "--quiet", "origin", "--delete", "feature")

    with pytest.raises(BranchDeletedFromGitHubError):
        BranchSync(work, PullRequestBranchesInMemory()).run()


def test_a_branch_the_sandbox_tracks_but_never_pushed_is_not_reported_deleted(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
):
    """
    A cloud session's sandbox creates the remote-tracking reference of the session's
    branch at setup, without pushing the branch.
    """
    policy = policy_in(repositories.clone(owned_url, "sandbox"), settings)
    git = policy.checkout.git
    git.run("switch", "--quiet", "--create", "claude/session-branch")
    git.run("update-ref", "refs/remotes/origin/claude/session-branch", "HEAD")

    BranchSync(policy, PullRequestBranchesInMemory()).run()


def test_a_cloned_branch_deleted_after_its_pull_request_is_reported_deleted(
    work: WritePolicy,
    repositories: RepositoriesByOwner,
    owned_url: str,
    settings: WorkflowSettings,
):
    """
    A clone writes no reflog entry for the branches it tracks, so the pull request
    opened from the branch shows it was on GitHub.
    """
    session = policy_in(repositories.clone(owned_url, "session"), settings)
    session.checkout.git.run("switch", "--quiet", "feature")
    deleter = repositories.clone(owned_url, "deleter").git
    deleter.run("push", "--quiet", "origin", "--delete", "feature")

    with pytest.raises(BranchDeletedFromGitHubError):
        BranchSync(session, PullRequestBranchesInMemory(frozenset({"feature"}))).run()


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
        BranchSync(work, PullRequestBranchesInMemory()).run()


def test_a_branch_is_not_reported_unpushed_when_github_cannot_be_reached(
    work: WritePolicy, repositories: RepositoriesByOwner
) -> None:
    BranchStart(work, "unpushed").run()
    cut_off_from_github(work, repositories)

    with pytest.raises(GitCommandFailed):
        BranchSync(work, PullRequestBranchesInMemory()).run()


# %% rewriting a draft's description


def test_a_draft_s_description_is_rewritten():
    github = DraftsInMemory(
        {1: RepositoriesByOwner.default_branch}, drafts=frozenset({1})
    )

    DescriptionRewrite(github, github, 1, "A new body").run()

    assert github.writes == ["set_description 1 A new body"]


@pytest.mark.parametrize(
    "github",
    [
        DraftsInMemory({1: RepositoriesByOwner.default_branch}),
        DraftsInMemory(
            {1: RepositoriesByOwner.default_branch},
            drafts=frozenset({1}),
            closed=frozenset({1}),
        ),
    ],
    ids=["ready for review", "closed"],
)
def test_a_pull_request_that_is_no_open_draft_keeps_its_description(
    github: DraftsInMemory,
):
    with pytest.raises(NotADraftError):
        DescriptionRewrite(github, github, 1, "A new body").run()

    assert github.writes == []


# %% cloning


def test_a_repository_of_the_owner_s_is_cloned_into_the_directory(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
):
    repository = Repository(settings.owner, RepositoriesByOwner.repository_name)
    directory = repositories.root / "session"

    RepositoryCloning(
        repository, directory, settings, f"file://{repositories.root}"
    ).run()

    [published] = repositories.branches(owned_url).splitlines()
    clone = GitCommandRunner(directory / repository.name)
    assert clone.commit_at("HEAD") == published.split()[0]


def test_somebody_else_s_repository_is_cloned_to_be_read(
    repositories: RepositoriesByOwner, foreign_url: str, settings: WorkflowSettings
):
    repository = Repository(
        RepositoriesByOwner.foreign_owner, RepositoriesByOwner.repository_name
    )
    directory = repositories.root / "session"

    RepositoryCloning(
        repository, directory, settings, f"file://{repositories.root}"
    ).run()

    [published] = repositories.branches(foreign_url).splitlines()
    clone = GitCommandRunner(directory / repository.name)
    assert clone.commit_at("HEAD") == published.split()[0]


def test_a_clone_carries_the_workflow_s_push_hook(
    repositories: RepositoriesByOwner, foreign_url: str, settings: WorkflowSettings
):
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
):
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
):
    checkout = repositories.clone(owned_url, "mine")
    repository = Repository(settings.owner, "another")
    arguments = WorkflowSession.parser().parse_args(
        [WorkflowCommand.CLONE, repository.full_name]
    )

    step = WorkflowSession(checkout.root, settings).step(arguments)

    assert step == RepositoryCloning(repository, checkout.root.parent, settings)


def test_a_clone_from_outside_a_checkout_goes_into_the_directory(
    tmp_path: Path, settings: WorkflowSettings
):
    repository = Repository(settings.owner, "another")
    arguments = WorkflowSession.parser().parse_args(
        [WorkflowCommand.CLONE, repository.full_name]
    )

    step = WorkflowSession(tmp_path, settings).step(arguments)

    assert step == RepositoryCloning(repository, tmp_path, settings)
