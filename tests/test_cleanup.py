"""
Tests for :mod:`github_workflow.cleanup`: only branches of closed pull requests and
discarded branches, still at the commit they were closed or discarded at, are ready for
deletion; they are deleted, or handed to the notes branch's workflow where deleting is
refused.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from basstler_domain_model.git.commands import GitCommandRunner, RemoteBranch
from basstler_domain_model.github.rest_models import RestPullRequest
from basstler_domain_model.github.vocabulary import PullRequestState

from github_workflow.cleanup import (
    BranchCleanup,
    BranchDiscard,
    BranchTips,
    CleanupReminder,
    DiscardedBranches,
    KeptBranches,
)
from github_workflow.exceptions import NothingToDiscardError, UndiscardableBranchError
from github_workflow.hooks import Tone
from github_workflow.locations import NotesFile
from github_workflow.notes.branch import NotesBranch
from github_workflow.remotes import OwnedRemotes
from github_workflow.policy import WritePolicy
from github_workflow.settings import WorkflowSettings
from github_workflow.work import BranchStart, CommitWork, PushWork

from .pull_requests import REPOSITORY, pull_request
from .repositories_by_owner import RepositoriesByOwner
from .test_work import (
    PullRequestsFromBranchesInMemory,
    RetiredInMemory,
    policy_in,
    write,
)

# %% helpers


def kept(tips: dict[str, str], *pull_requests: RestPullRequest) -> KeptBranches:
    """:param tips: Each branch and its commit.
    :param pull_requests: The repository's pull requests.
    :return: Them, with ``main`` and the notes branch protected."""
    return KeptBranches(
        tips, list(pull_requests), REPOSITORY, frozenset({"main", "notes"})
    )


# %% which branches are ready


def test_a_closed_pull_request_s_branch_is_ready():
    branches = kept(
        {"done": "a1"}, pull_request(1, "done", "a1", PullRequestState.CLOSED)
    )

    assert branches.ready() == ["done"]


def test_a_branch_with_new_commits_since_closing_is_kept():
    branches = kept(
        {"reused": "b2"}, pull_request(1, "reused", "b1", PullRequestState.CLOSED)
    )

    assert branches.ready() == []


def test_a_branch_with_an_open_pull_request_is_kept():
    branches = kept(
        {"again": "c1"},
        pull_request(1, "again", "c1", PullRequestState.CLOSED),
        pull_request(2, "again", "c1", PullRequestState.OPEN),
    )

    assert branches.ready() == []


def test_the_base_of_an_open_pull_request_is_kept():
    """
    Deleting the branch of a closed, unmerged lower pull request would close the open
    one stacked on it, for good.
    """
    branches = kept(
        {"lower": "h1", "upper": "h2"},
        pull_request(1, "lower", "h1", PullRequestState.CLOSED),
        pull_request(2, "upper", "h2", PullRequestState.OPEN, base="lower"),
    )

    assert branches.ready() == []


def test_a_branch_that_never_had_a_pull_request_is_kept():
    assert kept({"work": "d1"}).ready() == []


def test_a_protected_branch_is_never_ready():
    branches = kept(
        {"main": "e1", "notes": "e2"},
        pull_request(1, "main", "e1", PullRequestState.CLOSED),
        pull_request(2, "notes", "e2", PullRequestState.CLOSED),
    )

    assert branches.ready() == []


def test_a_pull_request_from_another_repository_says_nothing_about_this_one():
    branches = kept(
        {"same-name": "f1"},
        pull_request(1, "same-name", "f1", PullRequestState.CLOSED, "someone/fork"),
    )

    assert branches.ready() == []


def test_a_discarded_branch_still_at_its_commit_is_ready():
    branches = KeptBranches(
        {"tried": "g1"},
        [],
        REPOSITORY,
        frozenset({"main", "notes"}),
        DiscardedBranches({"tried": "g1"}),
    )

    assert branches.ready() == ["tried"]


def test_a_discarded_branch_with_new_commits_is_kept():
    branches = KeptBranches(
        {"tried": "g2"},
        [],
        REPOSITORY,
        frozenset({"main", "notes"}),
        DiscardedBranches({"tried": "g1"}),
    )

    assert branches.ready() == []


def test_the_discarded_list_reads_back_what_it_wrote():
    discarded = DiscardedBranches({"one": "a1", "two": "b2"})

    assert DiscardedBranches.from_text(discarded.to_text()) == discarded


def test_the_reminder_names_how_many_and_the_command():
    branches = kept(
        {"one": "a", "two": "b"},
        pull_request(1, "one", "a", PullRequestState.CLOSED),
        pull_request(2, "two", "b", PullRequestState.CLOSED),
    )

    [line] = CleanupReminder(branches).lines()

    assert "2 branches ready for deletion" in line.text
    assert line.tone is Tone.ACTION


# %% deleting them


def cleanup_in(
    repositories: RepositoriesByOwner, url: str, settings: WorkflowSettings
) -> tuple[BranchCleanup, GitCommandRunner]:
    """
    :param repositories: Where to clone.
    :param url: The owner's repository.
    :param settings: The workflow's settings.
    :return: A cleanup of a pushed branch whose pull request is closed, and the clone.
    """
    checkout = repositories.clone(url, "cleaner")
    git = checkout.git
    remote = OwnedRemotes.read(git, settings).chosen
    branch = RemoteBranch(remote.name, "closed-work")
    git.run("push", "--quiet", remote.name, f"HEAD:{branch.reference}")
    commit = git.commit_at("HEAD")
    branches = KeptBranches(
        {branch.name: commit},
        [
            pull_request(
                1,
                branch.name,
                commit,
                PullRequestState.CLOSED,
                remote.repository.full_name,
            )
        ],
        remote.repository.full_name,
        frozenset({RepositoriesByOwner.default_branch, settings.notes_branch}),
    )
    notes = NotesBranch.on(git, remote, settings)
    return BranchCleanup(git, remote, branches, notes), git


def test_a_ready_branch_is_deleted(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
):
    cleanup, git = cleanup_in(repositories, owned_url, settings)

    cleanup.run()

    assert "closed-work" not in repositories.branches(owned_url)


def test_a_branch_the_session_may_not_delete_is_listed_for_the_workflow(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
):
    bare = Path(owned_url.removeprefix("file://"))
    GitCommandRunner(bare).run("config", "receive.denyDeletes", "true")
    cleanup, git = cleanup_in(repositories, owned_url, settings)

    cleanup.run()

    notes = cleanup.notes
    notes.fetch()
    listed = BranchTips.from_text(notes.read(NotesFile.READY_FOR_DELETION.value))
    assert listed == BranchTips({"closed-work": cleanup.kept.tips["closed-work"]})
    assert settings.notes_branch in notes.read(NotesFile.DELETION_WORKFLOW.value)


# %% the deletion workflow


def listed_for_the_workflow(
    repositories: RepositoriesByOwner, url: str, settings: WorkflowSettings
) -> BranchCleanup:
    """
    :param repositories: Where to clone.
    :param url: The owner's repository, which refuses deletions from the session.
    :param settings: The workflow's settings.
    :return: The cleanup that listed ``closed-work`` for the deletion workflow.
    """
    bare = Path(url.removeprefix("file://"))
    GitCommandRunner(bare).run("config", "receive.denyDeletes", "true")
    cleanup, _ = cleanup_in(repositories, url, settings)
    cleanup.run()
    return cleanup


def run_deletion_workflow(
    repositories: RepositoriesByOwner, url: str, settings: WorkflowSettings
) -> None:
    """
    Run the deletion workflow's script as a push of the notes branch runs it: in a
    checkout of the notes branch, allowed to delete branches.

    :param repositories: Where to clone.
    :param url: The owner's repository.
    :param settings: The workflow's settings.
    """
    bare = Path(url.removeprefix("file://"))
    GitCommandRunner(bare).run("config", "receive.denyDeletes", "false")
    runner = repositories.clone(url, "actions-runner").git
    runner.run("checkout", "--quiet", settings.notes_branch)
    subprocess.run(
        [
            "bash",
            str(NotesFile.DELETION_SCRIPT.value),
            str(NotesFile.READY_FOR_DELETION.value),
            RepositoriesByOwner.default_branch,
            settings.notes_branch,
        ],
        cwd=runner.working_directory,
        check=True,
    )


def test_the_workflow_deletes_a_listed_branch_still_at_its_commit(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
):
    listed_for_the_workflow(repositories, owned_url, settings)

    run_deletion_workflow(repositories, owned_url, settings)

    assert "closed-work" not in repositories.branches(owned_url)


def test_the_workflow_empties_the_list_it_handled(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
):
    cleanup = listed_for_the_workflow(repositories, owned_url, settings)

    run_deletion_workflow(repositories, owned_url, settings)

    cleanup.notes.fetch()
    assert cleanup.notes.read(NotesFile.READY_FOR_DELETION.value) == ""


def test_the_workflow_keeps_a_listed_branch_that_moved_since(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
):
    listed_for_the_workflow(repositories, owned_url, settings)
    reused = repositories.clone(owned_url, "reuser").git
    reused.run("commit", "--quiet", "--allow-empty", "--message", "New work")
    reused.run("push", "--quiet", "origin", "HEAD:refs/heads/closed-work")

    run_deletion_workflow(repositories, owned_url, settings)

    moved = f"{reused.commit_at('HEAD')}\trefs/heads/closed-work"
    assert moved in repositories.branches(owned_url)


# %% discarding


def pushed_work(
    repositories: RepositoriesByOwner, url: str, settings: WorkflowSettings
) -> tuple[WritePolicy, NotesBranch]:
    """
    :param repositories: Where to clone.
    :param url: The owner's repository.
    :param settings: The workflow's settings.
    :return: The rules of a clone on a pushed branch ``tried``, and its notes branch.
    """
    policy = policy_in(repositories.clone(url, "thrower"), settings)
    BranchStart(policy, "tried").run()
    CommitWork(policy, "Try", [write(policy.checkout, "tried.txt")]).run()
    PushWork(policy).run()
    return policy, NotesBranch.on(policy.checkout.git, policy.remote, settings)


def discard(
    policy: WritePolicy,
    notes: NotesBranch,
    opened: list[RestPullRequest] | None = None,
    retired: RetiredInMemory | None = None,
    name: str | None = None,
) -> BranchDiscard:
    """
    :param policy: The rules of a clone on a pushed branch.
    :param notes: Its notes branch.
    :param opened: The pull requests opened from its branches.
    :param retired: Records the pull requests closed.
    :param name: The branch to discard, the checked-out one when ``None``.
    :return: The discard.
    """
    return BranchDiscard(
        policy,
        notes,
        PullRequestsFromBranchesInMemory(opened or []),
        retired or RetiredInMemory(),
        name,
    )


def test_a_discarded_branch_s_open_pull_request_is_closed(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
):
    policy, notes = pushed_work(repositories, owned_url, settings)
    retired = RetiredInMemory()
    opened = [
        pull_request(3, "tried"),
        pull_request(2, "tried", state=PullRequestState.CLOSED),
        pull_request(4, "elsewhere"),
    ]

    discard(policy, notes, opened, retired).run()

    assert [number for number, _ in retired.retired] == [3]


def test_a_discarded_branch_is_listed_with_its_commit(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
):
    policy, notes = pushed_work(repositories, owned_url, settings)

    discard(policy, notes).run()

    listed = notes.read(NotesFile.DISCARDED_BRANCHES.value)
    assert DiscardedBranches.from_text(listed) == DiscardedBranches(
        {"tried": policy.checkout.git.commit_at("tried")}
    )


def test_discarding_the_default_branch_is_refused(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
):
    policy, notes = pushed_work(repositories, owned_url, settings)

    with pytest.raises(UndiscardableBranchError):
        discard(policy, notes, name=policy.default_branch).run()


def test_discarding_a_branch_github_lacks_is_refused(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
):
    policy, notes = pushed_work(repositories, owned_url, settings)
    BranchStart(policy, "never-pushed").run()

    with pytest.raises(NothingToDiscardError):
        discard(policy, notes).run()
