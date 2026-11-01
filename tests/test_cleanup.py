"""
Tests for :mod:`github_workflow.cleanup`: only branches of closed pull requests, still
at the commit they were closed at, are ready for deletion; they are deleted, or handed
to the notes branch's workflow where deleting is refused.
"""

from __future__ import annotations

from pathlib import Path

from basstler_domain_model.git.commands import GitCommandRunner, RemoteBranch
from basstler_domain_model.github.pull_request_fields import (
    PullRequestHeadKey,
    PullRequestPayload,
)
from basstler_domain_model.github.vocabulary import IssueState, RestJSONKey

from github_workflow.cleanup import BranchCleanup, CleanupReminder, KeptBranches
from github_workflow.hooks import Tone
from github_workflow.locations import NotesFile
from github_workflow.notes.branch import NotesBranch
from github_workflow.remotes import OwnedRemotes
from github_workflow.settings import WorkflowSettings

from .repositories_by_owner import RepositoriesByOwner

REPOSITORY = "LucaKro/project"
"""
The full name of the repository the pull requests here are on.
"""

# %% helpers


def pull_request(
    number: int,
    branch: str,
    commit: str,
    state: IssueState,
    repository: str | None = REPOSITORY,
) -> PullRequestPayload:
    """
    :param number: The pull request.
    :param branch: The branch it merges.
    :param commit: The commit its head is at.
    :param state: Whether it is open.
    :param repository: The repository its head is in, ``None`` when deleted.
    :return: The pull request as GitHub lists it.
    """
    head_repository = (
        None if repository is None else {PullRequestHeadKey.FULL_NAME: repository}
    )
    return {
        RestJSONKey.NUMBER: number,
        RestJSONKey.STATE: state.value,
        RestJSONKey.HEAD: {
            PullRequestHeadKey.REFERENCE: branch,
            PullRequestHeadKey.HEAD_REPOSITORY: head_repository,
            RestJSONKey.SHA: commit,
        },
    }


def kept(tips: dict[str, str], *pull_requests: PullRequestPayload) -> KeptBranches:
    """:param tips: Each branch and its commit.
    :param pull_requests: The repository's pull requests.
    :return: Them, with ``main`` and the notes branch protected."""
    return KeptBranches(
        tips, list(pull_requests), REPOSITORY, frozenset({"main", "notes"})
    )


# %% which branches are ready


def test_a_closed_pull_request_s_branch_is_ready():
    branches = kept({"done": "a1"}, pull_request(1, "done", "a1", IssueState.CLOSED))

    assert branches.ready() == ["done"]


def test_a_branch_with_new_commits_since_closing_is_kept():
    branches = kept(
        {"reused": "b2"}, pull_request(1, "reused", "b1", IssueState.CLOSED)
    )

    assert branches.ready() == []


def test_a_branch_with_an_open_pull_request_is_kept():
    branches = kept(
        {"again": "c1"},
        pull_request(1, "again", "c1", IssueState.CLOSED),
        pull_request(2, "again", "c1", IssueState.OPEN),
    )

    assert branches.ready() == []


def test_a_branch_that_never_had_a_pull_request_is_kept():
    assert kept({"work": "d1"}).ready() == []


def test_a_protected_branch_is_never_ready():
    branches = kept(
        {"main": "e1", "notes": "e2"},
        pull_request(1, "main", "e1", IssueState.CLOSED),
        pull_request(2, "notes", "e2", IssueState.CLOSED),
    )

    assert branches.ready() == []


def test_a_pull_request_from_another_repository_says_nothing_about_this_one():
    branches = kept(
        {"same-name": "f1"},
        pull_request(1, "same-name", "f1", IssueState.CLOSED, "someone/fork"),
    )

    assert branches.ready() == []


def test_the_reminder_names_how_many_and_the_command():
    branches = kept(
        {"one": "a", "two": "b"},
        pull_request(1, "one", "a", IssueState.CLOSED),
        pull_request(2, "two", "b", IssueState.CLOSED),
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
                1, branch.name, commit, IssueState.CLOSED, remote.repository.full_name
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
    assert notes.read(NotesFile.READY_FOR_DELETION.value) == "closed-work"
    assert settings.notes_branch in notes.read(NotesFile.DELETION_WORKFLOW.value)
