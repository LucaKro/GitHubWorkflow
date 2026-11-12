"""
Tests for :mod:`domain_model.git.working_tree`: committing what is checked out, moving
the checked-out branch, and a merge from its start to its end.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from domain_model.git.commands import GitCommandRunner
from domain_model.git.revisions import BranchName, LocalBranch
from domain_model.git.working_tree import Merge, WorkingTree

from .git_checkouts import checkout, commit_on, head  # noqa: F401

# %% committing


def test_a_commit_holds_the_named_paths_only(
    checkout: GitCommandRunner,  # noqa: F811
) -> None:
    (checkout.working_directory / "kept.txt").write_text("kept\n")
    (checkout.working_directory / "left.txt").write_text("left\n")

    commit = WorkingTree(checkout).commit("Keep one", [Path("kept.txt")])

    assert checkout.run("show", "--name-only", "--format=", commit.hash) == "kept.txt"
    assert checkout.run("status", "--porcelain") == "?? left.txt"


@pytest.mark.parametrize("already_staged", [False, True])
def test_a_commit_of_a_removed_path_removes_it(
    checkout: GitCommandRunner, already_staged: bool  # noqa: F811
) -> None:
    (checkout.working_directory / "README.md").unlink()
    if already_staged:
        checkout.run("rm", "--quiet", "--cached", "README.md")

    commit = WorkingTree(checkout).commit("Remove the readme", [Path("README.md")])

    assert checkout.run("ls-tree", "--name-only", commit.hash) == ""


def test_a_commit_of_a_removed_directory_removes_its_files(
    checkout: GitCommandRunner,  # noqa: F811
) -> None:
    tree = WorkingTree(checkout)
    directory = checkout.working_directory / "plugin"
    directory.mkdir()
    (directory / "first.txt").write_text("first\n")
    (directory / "second.txt").write_text("second\n")
    tree.commit("Add the plugin", [Path("plugin")])
    for file in directory.iterdir():
        file.unlink()
    directory.rmdir()

    commit = tree.commit("Remove the plugin", [Path("plugin")])

    assert checkout.run("ls-tree", "--name-only", commit.hash) == "README.md"


def test_a_changed_tracked_file_is_an_uncommitted_change(
    checkout: GitCommandRunner,  # noqa: F811
) -> None:
    (checkout.working_directory / "README.md").write_text("edited\n")

    assert WorkingTree(checkout).has_uncommitted_changes()


def test_an_untracked_file_is_no_uncommitted_change(
    checkout: GitCommandRunner,  # noqa: F811
) -> None:
    (checkout.working_directory / "new.txt").write_text("new\n")

    assert not WorkingTree(checkout).has_uncommitted_changes()


def test_a_detached_head_has_no_checked_out_branch(
    checkout: GitCommandRunner,  # noqa: F811
) -> None:
    checkout.run("switch", "--quiet", "--detach")

    assert WorkingTree(checkout).checked_out_branch() is None


# %% moving the checked-out branch


def test_a_branch_behind_fast_forwards(
    checkout: GitCommandRunner,  # noqa: F811
) -> None:
    commit_on(checkout, "ahead", "main", "ahead.txt")
    LocalBranch(checkout, BranchName("main")).switch()
    ahead = LocalBranch(checkout, BranchName("ahead"))

    moved = WorkingTree(checkout).fast_forward(ahead)

    assert (moved.succeeded, LocalBranch(checkout, BranchName("main")).commit()) == (
        True,
        ahead.commit(),
    )


def test_a_diverged_branch_does_not_fast_forward(
    checkout: GitCommandRunner,  # noqa: F811
) -> None:
    commit_on(checkout, "other", "main", "other.txt")
    commit_on(checkout, "mine", "main", "mine.txt")
    before = head(checkout)

    moved = WorkingTree(checkout).fast_forward(
        LocalBranch(checkout, BranchName("other"))
    )

    assert (moved.succeeded, head(checkout)) == (False, before)


def test_a_kept_reset_keeps_uncommitted_changes(
    checkout: GitCommandRunner,  # noqa: F811
) -> None:
    commit_on(checkout, "rewritten", "main", "rewritten.txt")
    commit_on(checkout, "mine", "main", "mine.txt")
    (checkout.working_directory / "README.md").write_text("edited\n")
    rewritten = LocalBranch(checkout, BranchName("rewritten"))

    WorkingTree(checkout).reset_kept(rewritten)

    assert head(checkout) == rewritten.commit().hash
    assert (checkout.working_directory / "README.md").read_text() == "edited\n"


# %% a merge


def diverged_on_readme(git: GitCommandRunner) -> None:
    """:param git: A checkout, left on ``mine``, which changes ``README.md`` one way
    while ``other`` changes it another."""
    for branch, text in (("other", "theirs\n"), ("mine", "ours\n")):
        git.run("switch", "--quiet", "--create", branch, "main")
        (git.working_directory / "README.md").write_text(text)
        WorkingTree(git).commit(f"Change README on {branch}", [Path("README.md")])


def test_a_branch_merges_another_s_commits_with_the_message_given(
    checkout: GitCommandRunner,  # noqa: F811
) -> None:
    commit_on(checkout, "other", "main", "other.txt")
    commit_on(checkout, "mine", "main", "mine.txt")
    other = LocalBranch(checkout, BranchName("other"))

    merged = Merge(WorkingTree(checkout)).start(other, "Merge other into mine")

    assert (merged.succeeded, other.is_contained_in(WorkingTree(checkout).head())) == (
        True,
        True,
    )
    assert (
        checkout.run("log", "--max-count=1", "--format=%B") == "Merge other into mine"
    )


def test_a_conflicting_merge_names_its_files_and_is_undone(
    checkout: GitCommandRunner,  # noqa: F811
) -> None:
    diverged_on_readme(checkout)
    before = head(checkout)
    merge = Merge(WorkingTree(checkout))

    merged = merge.start(
        LocalBranch(checkout, BranchName("other")), "Merge other into mine"
    )
    conflicted = merge.conflicted_files()
    merge.abort()

    assert (merged.succeeded, conflicted, head(checkout)) == (
        False,
        ["README.md"],
        before,
    )
    assert checkout.run("status", "--porcelain") == ""


@pytest.fixture
def conflicting(checkout: GitCommandRunner) -> Merge:  # noqa: F811
    """:return: A merge of ``other`` into ``mine``, in progress and conflicting in
    ``README.md``."""
    diverged_on_readme(checkout)
    merge = Merge(WorkingTree(checkout))
    merge.start(LocalBranch(checkout, BranchName("other")), "Merge other into mine")
    return merge


def test_a_conflicting_merge_is_in_progress(conflicting: Merge) -> None:
    assert conflicting.in_progress()


def test_no_merge_is_in_progress_in_a_plain_checkout(
    checkout: GitCommandRunner,  # noqa: F811
) -> None:
    assert not Merge(WorkingTree(checkout)).in_progress()


def test_a_merge_in_progress_keeps_the_message_it_was_started_with(
    conflicting: Merge,
) -> None:
    assert conflicting.message() == "Merge other into mine"


def test_a_resolved_merge_is_committed_with_both_parents(conflicting: Merge) -> None:
    git = conflicting.tree.git
    mine = head(git)
    (git.working_directory / "README.md").write_text("both\n")
    conflicting.tree.stage([Path("README.md")])

    commit = conflicting.tree.commit_staged(conflicting.message())

    parents = git.run("rev-list", "--parents", "--max-count=1", commit.hash).split()
    assert parents[1:] == [mine, LocalBranch(git, BranchName("other")).commit().hash]
