"""
Tests for :mod:`domain_model.git.revisions`: commits, local branches, committing files
without a checkout, and how two revisions relate.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from domain_model.git.commands import GitCommandRunner
from domain_model.git.exceptions import GitCommandFailed, UnresolvableReferenceError
from domain_model.git.references import ReferenceNamespace
from domain_model.git.revisions import (
    BranchName,
    Commit,
    CommitHash,
    LocalBranch,
    TextFiles,
)
from domain_model.git.working_tree import WorkingTree

from .git_checkouts import checkout, create_branch_with_commit, head  # noqa: F401

# %% a commit's name


def test_a_commit_hash_is_abbreviated_to_its_leading_digits() -> None:
    commit = CommitHash("0123456789abcdef")

    assert commit.abbreviated == commit[: CommitHash.abbreviation_length]


def test_a_branch_name_s_reference_is_filed_among_the_branches() -> None:
    name = BranchName("feature/x")

    assert name.reference == f"{ReferenceNamespace.BRANCHES}{name}"


# %% resolving a revision


def test_a_branch_resolves_to_the_commit_it_is_at(
    checkout: GitCommandRunner,  # noqa: F811
) -> None:
    assert LocalBranch(checkout, BranchName("main")).commit().hash == head(checkout)


def test_a_branch_that_does_not_exist_resolves_to_no_commit(
    checkout: GitCommandRunner,  # noqa: F811
) -> None:
    assert LocalBranch(checkout, BranchName("absent")).commit_or_none() is None


def test_a_branch_that_does_not_exist_is_refused_where_a_commit_is_needed(
    checkout: GitCommandRunner,  # noqa: F811
) -> None:
    with pytest.raises(UnresolvableReferenceError):
        LocalBranch(checkout, BranchName("absent")).commit()


def test_a_revision_is_contained_in_a_descendant_and_not_the_other_way(
    checkout: GitCommandRunner,  # noqa: F811
) -> None:
    create_branch_with_commit(checkout, "ahead", "main", "ahead.txt")
    main, ahead = LocalBranch(checkout, BranchName("main")), LocalBranch(
        checkout, BranchName("ahead")
    )

    assert (main.is_contained_in(ahead), ahead.is_contained_in(main)) == (True, False)


def test_the_commits_one_revision_holds_beyond_another_are_counted(
    checkout: GitCommandRunner,  # noqa: F811
) -> None:
    create_branch_with_commit(checkout, "ahead", "main", "first.txt")
    create_branch_with_commit(checkout, "further", "ahead", "second.txt")
    main, further = LocalBranch(checkout, BranchName("main")), LocalBranch(
        checkout, BranchName("further")
    )

    assert (further.commits_ahead(main), main.commits_ahead(further)) == (2, 0)


@pytest.mark.parametrize(
    "theirs, conflicts", [("theirs\n", True), ("start\n", False)], ids=str
)
def test_a_merge_conflicts_only_where_both_sides_change_a_file(
    checkout: GitCommandRunner, theirs: str, conflicts: bool  # noqa: F811
) -> None:
    for branch, text in (("other", theirs), ("mine", "ours\n")):
        checkout.run("switch", "--quiet", "--create", branch, "main")
        (checkout.working_directory / "README.md").write_text(text)
        checkout.run("commit", "--quiet", "--allow-empty", "--all", "--message", branch)
    mine, other = LocalBranch(checkout, BranchName("mine")), LocalBranch(
        checkout, BranchName("other")
    )

    assert mine.conflicts_when_merged(other) == conflicts


def test_a_revision_s_file_is_read_as_it_records_it(
    checkout: GitCommandRunner,  # noqa: F811
) -> None:
    (checkout.working_directory / "README.md").write_text("changed\n")
    main = LocalBranch(checkout, BranchName("main"))

    assert (main.file_text(Path("README.md")), main.file_text(Path("absent"))) == (
        "start\n",
        None,
    )


# %% files to commit


def test_combined_files_hold_both_with_the_later_text_winning() -> None:
    first = TextFiles({Path("one.md"): "one\n", Path("both.md"): "first\n"})
    later = TextFiles({Path("both.md"): "later\n"})

    assert first.combine(later) == TextFiles(
        {Path("one.md"): "one\n", Path("both.md"): "later\n"}
    )


def test_files_list_their_paths_in_the_order_given() -> None:
    files = TextFiles({Path("b.md"): "b\n", Path("a.md"): "a\n"})

    assert files.paths == [Path("b.md"), Path("a.md")]


# %% committing without a checkout


def test_a_commit_of_files_leaves_the_checkout_untouched(
    checkout: GitCommandRunner,  # noqa: F811
) -> None:
    before = checkout.run("status", "--porcelain")

    commit = Commit.write_root(
        checkout, TextFiles({Path("notes.md"): "a note\n"}), "Save"
    )

    assert commit.file_text(Path("notes.md")) == "a note\n"
    assert checkout.run("status", "--porcelain") == before


def test_a_root_commit_has_no_parent(
    checkout: GitCommandRunner,  # noqa: F811
) -> None:
    commit = Commit.write_root(checkout, TextFiles({}), "Start over")

    assert not checkout.attempt("rev-parse", "--verify", f"{commit.hash}^").succeeded


def test_a_commit_on_a_parent_keeps_the_parent_s_files(
    checkout: GitCommandRunner,  # noqa: F811
) -> None:
    parent = Commit.write_root(
        checkout, TextFiles({Path("notes.md"): "a note\n"}), "Save"
    )

    commit = parent.write_child(
        TextFiles({Path("progress/a.md"): "progress\n"}), "Save"
    )

    assert commit.file_text(Path("notes.md")) == "a note\n"
    assert checkout.run("rev-parse", f"{commit.hash}^") == parent.hash


# %% writing out a commit's files


def test_a_commit_s_files_are_written_into_a_directory(
    checkout: GitCommandRunner, tmp_path: Path  # noqa: F811
) -> None:
    start = WorkingTree(checkout).head()
    create_branch_with_commit(checkout, "later", "main", "later.txt")
    destination = tmp_path / "files"

    start.export_files(destination)

    assert sorted(path.name for path in destination.iterdir()) == ["README.md"]
    assert (destination / "README.md").read_text() == "start\n"


def test_writing_out_a_commit_s_files_leaves_the_checkout_untouched(
    checkout: GitCommandRunner, tmp_path: Path  # noqa: F811
) -> None:
    (checkout.working_directory / "README.md").write_text("changed\n")
    before = checkout.run("status", "--porcelain")

    WorkingTree(checkout).head().export_files(tmp_path / "files")

    assert checkout.run("status", "--porcelain") == before


# %% local branches


def test_a_created_branch_is_checked_out_at_its_start(
    checkout: GitCommandRunner,  # noqa: F811
) -> None:
    start = head(checkout)

    LocalBranch(checkout, BranchName("feature")).create(
        LocalBranch(checkout, BranchName("main"))
    )

    tree = WorkingTree(checkout)
    assert (tree.checked_out_branch(), tree.head().hash) == (
        LocalBranch(checkout, BranchName("feature")),
        start,
    )


def test_creating_a_branch_that_exists_is_refused(
    checkout: GitCommandRunner,  # noqa: F811
) -> None:
    main = LocalBranch(checkout, BranchName("main"))

    with pytest.raises(GitCommandFailed):
        main.create(main)


def test_switching_checks_the_branch_out(
    checkout: GitCommandRunner,  # noqa: F811
) -> None:
    create_branch_with_commit(checkout, "feature", "main", "feature.txt")

    LocalBranch(checkout, BranchName("main")).switch()

    assert WorkingTree(checkout).checked_out_branch() == LocalBranch(
        checkout, BranchName("main")
    )


def test_a_branch_not_checked_out_is_fast_forwarded(
    checkout: GitCommandRunner,  # noqa: F811
) -> None:
    create_branch_with_commit(checkout, "ahead", "main", "ahead.txt")
    main, ahead = LocalBranch(checkout, BranchName("main")), LocalBranch(
        checkout, BranchName("ahead")
    )

    moved = main.fast_forward(ahead)

    assert (moved.succeeded, main.commit()) == (True, ahead.commit())


def test_a_branch_with_commits_the_target_lacks_is_not_moved(
    checkout: GitCommandRunner,  # noqa: F811
) -> None:
    create_branch_with_commit(checkout, "ahead", "main", "ahead.txt")
    create_branch_with_commit(checkout, "diverged", "main", "own.txt")
    diverged = LocalBranch(checkout, BranchName("diverged"))
    before = diverged.commit()
    LocalBranch(checkout, BranchName("ahead")).switch()

    moved = diverged.fast_forward(LocalBranch(checkout, BranchName("ahead")))

    assert (moved.succeeded, diverged.commit()) == (False, before)


def test_the_checked_out_branch_is_not_moved(
    checkout: GitCommandRunner,  # noqa: F811
) -> None:
    create_branch_with_commit(checkout, "ahead", "main", "ahead.txt")
    main = LocalBranch(checkout, BranchName("main"))
    main.switch()
    before = main.commit()

    moved = main.fast_forward(LocalBranch(checkout, BranchName("ahead")))

    assert (moved.succeeded, main.commit()) == (False, before)


# %% a branch's settings


def test_a_branch_setting_reads_back_what_was_written(
    checkout: GitCommandRunner,  # noqa: F811
) -> None:
    branch = LocalBranch(checkout, BranchName("feature/x"))

    branch.write_setting("base", "SUTURO/project:main")

    assert branch.read_setting("base") == "SUTURO/project:main"


def test_a_branch_setting_never_written_reads_none(
    checkout: GitCommandRunner,  # noqa: F811
) -> None:
    assert LocalBranch(checkout, BranchName("main")).read_setting("base") is None
