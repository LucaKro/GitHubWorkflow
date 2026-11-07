"""
Tests for the git side of working with branches: the remotes, committing files without a
checkout, and replaying a stack of branches onto a moved base.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from basstler_domain_model.environment import GitIdentityVariable, GitVariable
from basstler_domain_model.git.exceptions import (
    GitCommandFailed,
    MalformedReferenceUpdateError,
)
from basstler_domain_model.git.commands import (
    GitCommandRunner,
    GitIdentity,
    ProposedPush,
    ReferenceUpdate,
    RemoteBranch,
    RemoteName,
)
from basstler_domain_model.locations import GitStateFile
from basstler_domain_model.repository import Repository

# %% fixtures


@pytest.fixture
def checkout(tmp_path: Path) -> GitCommandRunner:
    """:return: A checkout with one commit on ``main``, and an identity to commit as."""
    git = GitCommandRunner(tmp_path / "checkout")
    git.working_directory.mkdir()
    git.run("init", "--quiet", "--initial-branch=main")
    git.run("config", "user.name", "Test Author")
    git.run("config", "user.email", "test.author@example.com")
    (git.working_directory / "README.md").write_text("start\n")
    git.run("add", "README.md")
    git.run("commit", "--quiet", "--message", "Start")
    return git


def commit_on(git: GitCommandRunner, branch: str, start: str, name: str) -> None:
    """
    :param git: The checkout.
    :param branch: The branch to create and commit on.
    :param start: Where it starts.
    :param name: The file the commit adds, and its message.
    """
    git.run("switch", "--quiet", "--create", branch, start)
    (git.working_directory / name).write_text(f"{name}\n")
    git.run("add", name)
    git.run("commit", "--quiet", "--message", name)


# %% remotes


def test_a_remote_names_the_repository_it_pushes_to(checkout: GitCommandRunner):
    checkout.run(
        "remote", "add", "origin", "https://github.com/an-owner/a-repository.git"
    )

    [remote] = checkout.remotes()

    assert remote.repository is not None
    assert remote.repository.full_name == "an-owner/a-repository"


def test_a_remote_that_names_no_repository_has_none(checkout: GitCommandRunner):
    checkout.run("remote", "add", "local", "/a/plain/path")

    assert checkout.remotes()[0].repository is None


@pytest.fixture
def cloned(checkout: GitCommandRunner, tmp_path: Path) -> GitCommandRunner:
    """:return: A clone of a bare repository whose default branch is ``trunk``."""
    remote = tmp_path / "trunk.git"
    checkout.run("init", "--quiet", "--bare", "--initial-branch=trunk", str(remote))
    checkout.run("push", "--quiet", str(remote), "HEAD:refs/heads/trunk")
    return GitCommandRunner.clone(str(remote), tmp_path / "clone")


def test_a_remote_s_default_branch_is_the_one_its_head_names(
    cloned: GitCommandRunner,
):
    assert cloned.remote_default_branch(RemoteName.ORIGIN) == "trunk"


def test_an_unreachable_remote_s_default_branch_is_the_one_last_fetched(
    cloned: GitCommandRunner, tmp_path: Path
):
    cloned.run("remote", "set-url", RemoteName.ORIGIN, str(tmp_path / "gone.git"))

    assert cloned.remote_default_branch(RemoteName.ORIGIN) == "trunk"


def test_an_unreachable_remote_never_fetched_has_no_known_default_branch(
    checkout: GitCommandRunner, tmp_path: Path
):
    checkout.run("remote", "add", RemoteName.ORIGIN, str(tmp_path / "gone.git"))

    assert checkout.remote_default_branch(RemoteName.ORIGIN) is None


@pytest.fixture
def published(checkout: GitCommandRunner, tmp_path: Path) -> RemoteBranch:
    """:return: ``main``, pushed to a bare ``origin`` of the checkout."""
    remote = tmp_path / "remote.git"
    checkout.run("init", "--quiet", "--bare", str(remote))
    checkout.run("remote", "add", RemoteName.ORIGIN, str(remote))
    branch = RemoteBranch(RemoteName.ORIGIN, "main")
    checkout.run("push", "--quiet", branch.remote, f"HEAD:{branch.reference}")
    return branch


def test_a_pushed_branch_is_on_its_remote(
    checkout: GitCommandRunner, published: RemoteBranch
):
    assert checkout.has_remote_branch(published)


def test_a_branch_never_pushed_is_not_on_the_remote(
    checkout: GitCommandRunner, published: RemoteBranch
):
    assert not checkout.has_remote_branch(RemoteBranch(published.remote, "elsewhere"))


def upstream(git: GitCommandRunner, branch: str) -> str | None:
    """
    :param git: The checkout.
    :param branch: A local branch.
    :return: The branch it tracks, ``None`` when it tracks none.
    """
    found = git.attempt("rev-parse", "--abbrev-ref", f"{branch}@{{upstream}}")
    return found.output if found.succeeded else None


def test_a_branch_created_from_a_remote_s_branch_tracks_none(
    checkout: GitCommandRunner, published: RemoteBranch
):
    checkout.run("fetch", "--quiet", published.remote)

    checkout.create_branch("feature", f"{published.remote}/{published.name}")

    assert upstream(checkout, "feature") is None


def test_a_push_that_sets_the_upstream_makes_the_branch_track_where_it_went(
    checkout: GitCommandRunner, published: RemoteBranch
):
    checkout.create_branch("feature", "main")
    pushed = RemoteBranch(published.remote, "feature")

    checkout.push(
        ProposedPush(pushed.remote, f"feature:{pushed.reference}", sets_upstream=True)
    )

    assert upstream(checkout, "feature") == f"{pushed.remote}/{pushed.name}"


def test_a_plain_push_leaves_the_branch_tracking_none(
    checkout: GitCommandRunner, published: RemoteBranch
):
    checkout.create_branch("feature", "main")
    pushed = RemoteBranch(published.remote, "feature")

    checkout.push(ProposedPush(pushed.remote, f"feature:{pushed.reference}"))

    assert upstream(checkout, "feature") is None


def test_a_deleted_branch_is_gone_from_its_remote(
    checkout: GitCommandRunner, published: RemoteBranch
):
    deleted = checkout.delete_remote_branch(published)

    assert deleted.succeeded
    assert not checkout.has_remote_branch(published)


def test_branches_still_at_their_commits_are_deleted_in_one_push(
    checkout: GitCommandRunner, published: RemoteBranch
):
    others = [RemoteBranch(published.remote, name) for name in ("second", "third")]
    checkout.run(
        "push",
        "--quiet",
        published.remote,
        *[f"HEAD:{branch.reference}" for branch in others],
    )
    commit = checkout.commit_at("HEAD")

    refused = checkout.delete_remote_branches(
        published.remote,
        {branch.name: commit for branch in [published, *others]},
    )

    assert (refused, [checkout.has_remote_branch(b) for b in [published, *others]]) == (
        [],
        [False, False, False],
    )


def test_a_branch_that_moved_is_kept_and_named(
    checkout: GitCommandRunner, published: RemoteBranch
):
    before = checkout.run("rev-parse", "HEAD~0").strip()
    checkout.run("commit", "--quiet", "--allow-empty", "--message", "Move on")
    checkout.run("push", "--quiet", published.remote, f"HEAD:{published.reference}")

    refused = checkout.delete_remote_branches(
        published.remote, {published.name: before}
    )

    assert (refused, checkout.has_remote_branch(published)) == ([published.name], True)


def test_a_fetched_branch_moves_only_its_tracking_reference(
    checkout: GitCommandRunner, published: RemoteBranch
):
    checkout.fetch_branch(published)

    assert checkout.commit_at(published.tracking_reference) == checkout.commit_at(
        "HEAD"
    )


def test_a_branch_is_fetched_from_a_url_into_its_remote_s_tracking_reference(
    checkout: GitCommandRunner, published: RemoteBranch, tmp_path: Path
):
    elsewhere = RemoteBranch("elsewhere", published.name)

    checkout.fetch_branch(elsewhere, str(tmp_path / "remote.git")).raise_if_failed()

    assert checkout.commit_at(elsewhere.tracking_reference) == checkout.commit_at(
        "HEAD"
    )


def test_every_branch_of_a_remote_is_listed_with_its_tip(
    checkout: GitCommandRunner, published: RemoteBranch
):
    checkout.run("commit", "--quiet", "--allow-empty", "--message", "Move on")
    checkout.run("push", "--quiet", published.remote, "HEAD:refs/heads/a/nested")

    assert checkout.remote_branch_tips(published.remote) == {
        "a/nested": checkout.commit_at("HEAD"),
        published.name: checkout.commit_at("HEAD~1"),
    }


def test_a_push_skipping_the_hook_is_not_refused_by_it(
    checkout: GitCommandRunner, published: RemoteBranch
):
    hook = checkout.git_path(Path("hooks/pre-push"))
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)
    pushed = RemoteBranch(published.remote, "feature")

    refused = checkout.push(ProposedPush(pushed.remote, f"HEAD:{pushed.reference}"))
    skipped = checkout.push(
        ProposedPush(pushed.remote, f"HEAD:{pushed.reference}", runs_push_hook=False)
    )

    assert (refused.succeeded, skipped.succeeded) == (False, True)


def test_the_reflog_names_what_wrote_a_reference(
    checkout: GitCommandRunner, published: RemoteBranch
):
    assert checkout.reflog_entries(published.tracking_reference) == ["update by push"]


def test_a_reference_without_a_reflog_has_no_entries(checkout: GitCommandRunner):
    assert checkout.reflog_entries("refs/remotes/nowhere/main") == []


def test_a_branch_only_ending_in_another_s_reference_is_not_its_tip(
    checkout: GitCommandRunner, published: RemoteBranch
) -> None:
    absent = RemoteBranch(published.remote, "absent")
    checkout.run(
        "push", "--quiet", published.remote, f"HEAD:refs/heads/a/{absent.reference}"
    )

    assert checkout.remote_branch_tip(absent) is None


def test_a_git_result_keeps_the_command_as_invoked(
    checkout: GitCommandRunner,
) -> None:
    assert checkout.attempt("version").arguments == ("git", "version")


# %% committing without a checkout


def test_a_commit_of_files_leaves_the_checkout_untouched(checkout: GitCommandRunner):
    before = checkout.run("status", "--porcelain")

    commit = checkout.commit_files(None, {Path("notes.md"): "a note\n"}, "Save")

    assert checkout.run("show", f"{commit}:notes.md") == "a note"
    assert checkout.run("status", "--porcelain") == before


def test_a_commit_on_a_parent_keeps_the_parent_s_files(checkout: GitCommandRunner):
    parent = checkout.commit_files(None, {Path("notes.md"): "a note\n"}, "Save")

    commit = checkout.commit_files(
        parent, {Path("progress/a.md"): "progress\n"}, "Save"
    )

    assert checkout.run("show", f"{commit}:notes.md") == "a note"
    assert checkout.run("rev-parse", f"{commit}^") == parent


# %% writing out a commit's files


def test_a_commit_s_files_are_written_into_a_directory(
    checkout: GitCommandRunner, tmp_path: Path
):
    start = checkout.commit_at("HEAD")
    commit_on(checkout, "later", "main", "later.txt")
    destination = tmp_path / "files"

    checkout.export_files(start, destination)

    assert sorted(path.name for path in destination.iterdir()) == ["README.md"]
    assert (destination / "README.md").read_text() == "start\n"


def test_writing_out_a_commit_s_files_leaves_the_checkout_untouched(
    checkout: GitCommandRunner, tmp_path: Path
):
    (checkout.working_directory / "README.md").write_text("changed\n")
    before = checkout.run("status", "--porcelain")

    checkout.export_files("HEAD", tmp_path / "files")

    assert checkout.run("status", "--porcelain") == before


# %% restacking


def test_a_stack_is_replayed_onto_its_moved_base_branch_by_branch(
    checkout: GitCommandRunner,
):
    commit_on(checkout, "lower", "main", "lower.txt")
    commit_on(checkout, "upper", "lower", "upper.txt")
    commit_on(checkout, "base-moved", "main", "base.txt")

    result = checkout.rebase_stack("base-moved", "upper")

    assert result.succeeded
    assert checkout.contains("base-moved", "lower")
    assert checkout.contains("lower", "upper")


# %% working on branches


def test_a_created_branch_is_checked_out_at_its_start(checkout: GitCommandRunner):
    start = checkout.commit_at("HEAD")

    checkout.create_branch("feature", "main")

    assert checkout.checked_out_branch() == "feature"
    assert checkout.commit_at("HEAD") == start


def test_creating_a_branch_that_exists_is_refused(checkout: GitCommandRunner):
    with pytest.raises(GitCommandFailed):
        checkout.create_branch("main", "main")


def test_a_branch_not_checked_out_is_fast_forwarded(checkout: GitCommandRunner):
    commit_on(checkout, "ahead", "main", "ahead.txt")
    checkout.create_branch("feature", "ahead")

    moved = checkout.fast_forward_branch("main", "ahead")

    assert moved.succeeded
    assert checkout.commit_at("main") == checkout.commit_at("ahead")


def test_a_branch_with_commits_the_reference_lacks_is_not_moved(
    checkout: GitCommandRunner,
):
    commit_on(checkout, "ahead", "main", "ahead.txt")
    commit_on(checkout, "diverged", "main", "own.txt")
    before = checkout.commit_at("diverged")
    checkout.switch_to("ahead")

    moved = checkout.fast_forward_branch("diverged", "ahead")

    assert not moved.succeeded
    assert checkout.commit_at("diverged") == before


def test_the_checked_out_branch_is_not_moved(checkout: GitCommandRunner):
    commit_on(checkout, "ahead", "main", "ahead.txt")
    checkout.switch_to("main")
    before = checkout.commit_at("main")

    moved = checkout.fast_forward_branch("main", "ahead")

    assert not moved.succeeded
    assert checkout.commit_at("main") == before


def test_switching_checks_the_branch_out(checkout: GitCommandRunner):
    commit_on(checkout, "feature", "main", "feature.txt")

    checkout.switch_to("main")

    assert checkout.checked_out_branch() == "main"


def test_a_commit_holds_the_named_paths_only(checkout: GitCommandRunner):
    (checkout.working_directory / "kept.txt").write_text("kept\n")
    (checkout.working_directory / "left.txt").write_text("left\n")

    commit = checkout.commit("Keep one", [Path("kept.txt")])

    assert checkout.run("show", "--name-only", "--format=", commit) == "kept.txt"
    assert checkout.run("status", "--porcelain") == "?? left.txt"


def test_a_branch_behind_fast_forwards(checkout: GitCommandRunner):
    commit_on(checkout, "ahead", "main", "ahead.txt")
    checkout.switch_to("main")

    assert checkout.fast_forward("ahead").succeeded
    assert checkout.commit_at("main") == checkout.commit_at("ahead")


def test_a_diverged_branch_does_not_fast_forward(checkout: GitCommandRunner):
    commit_on(checkout, "other", "main", "other.txt")
    commit_on(checkout, "mine", "main", "mine.txt")

    assert not checkout.fast_forward("other").succeeded
    assert checkout.contains("mine", "HEAD")


def test_a_branch_merges_another_s_commits_with_the_message_given(
    checkout: GitCommandRunner,
):
    commit_on(checkout, "other", "main", "other.txt")
    commit_on(checkout, "mine", "main", "mine.txt")

    merged = checkout.merge("other", "Merge other into mine")

    assert merged.succeeded
    assert checkout.contains("other", "HEAD")
    assert (
        checkout.run("log", "--max-count=1", "--format=%B") == "Merge other into mine"
    )


def test_a_conflicting_merge_names_its_files_and_is_undone(
    checkout: GitCommandRunner,
):
    for branch, text in (("other", "theirs\n"), ("mine", "ours\n")):
        checkout.run("switch", "--quiet", "--create", branch, "main")
        (checkout.working_directory / "README.md").write_text(text)
        checkout.commit(f"Change README on {branch}", [Path("README.md")])
    before = checkout.commit_at("HEAD")

    merged = checkout.merge("other", "Merge other into mine")
    conflicted = checkout.conflicted_files()
    checkout.abort_merge()

    assert not merged.succeeded
    assert conflicted == ["README.md"]
    assert checkout.commit_at("HEAD") == before
    assert checkout.run("status", "--porcelain") == ""


@pytest.fixture
def conflicting(checkout: GitCommandRunner) -> GitCommandRunner:
    """:return: The checkout, on ``mine``, in the middle of a merge of ``other``
    conflicting in ``README.md``."""
    for branch, text in (("other", "theirs\n"), ("mine", "ours\n")):
        checkout.run("switch", "--quiet", "--create", branch, "main")
        (checkout.working_directory / "README.md").write_text(text)
        checkout.commit(f"Change README on {branch}", [Path("README.md")])
    checkout.merge("other", "Merge other into mine")
    return checkout


def test_a_conflicting_merge_is_in_progress(conflicting: GitCommandRunner):
    assert conflicting.merge_in_progress()


def test_no_merge_is_in_progress_in_a_plain_checkout(checkout: GitCommandRunner):
    assert not checkout.merge_in_progress()


def test_a_merge_in_progress_keeps_the_message_it_was_started_with(
    conflicting: GitCommandRunner,
):
    assert conflicting.merge_message() == "Merge other into mine"


def test_a_resolved_merge_is_committed_with_both_parents(
    conflicting: GitCommandRunner,
):
    (conflicting.working_directory / "README.md").write_text("both\n")
    conflicting.stage([Path("README.md")])

    commit = conflicting.commit_staged(conflicting.merge_message())

    assert conflicting.parents_of(commit) == (
        conflicting.commit_at("HEAD~1"),
        conflicting.commit_at("other"),
    )


def test_a_changed_tracked_file_is_an_uncommitted_change(checkout: GitCommandRunner):
    (checkout.working_directory / "README.md").write_text("edited\n")

    assert checkout.has_uncommitted_changes()


def test_an_untracked_file_is_no_uncommitted_change(checkout: GitCommandRunner):
    (checkout.working_directory / "new.txt").write_text("new\n")

    assert not checkout.has_uncommitted_changes()


def test_the_commits_one_reference_holds_beyond_another_are_counted(
    checkout: GitCommandRunner,
):
    commit_on(checkout, "ahead", "main", "first.txt")
    (checkout.working_directory / "second.txt").write_text("second\n")
    checkout.commit("second.txt", [Path("second.txt")])

    assert (
        checkout.commits_between("main", "ahead"),
        checkout.commits_between("ahead", "main"),
    ) == (2, 0)


def test_a_git_directory_file_is_found_inside_the_checkout_s_git_directory(
    checkout: GitCommandRunner,
):
    assert checkout.git_path(GitStateFile.MERGE_MESSAGE) == (
        checkout.working_directory / ".git" / GitStateFile.MERGE_MESSAGE
    )


def test_a_kept_reset_keeps_uncommitted_changes(checkout: GitCommandRunner):
    commit_on(checkout, "rewritten", "main", "rewritten.txt")
    commit_on(checkout, "mine", "main", "mine.txt")
    (checkout.working_directory / "README.md").write_text("edited\n")

    checkout.reset_kept("rewritten")

    assert checkout.commit_at("HEAD") == checkout.commit_at("rewritten")
    assert (checkout.working_directory / "README.md").read_text() == "edited\n"


@pytest.mark.parametrize("already_staged", [False, True])
def test_a_commit_of_a_removed_path_removes_it(
    checkout: GitCommandRunner, already_staged: bool
):
    (checkout.working_directory / "README.md").unlink()
    if already_staged:
        checkout.run("rm", "--quiet", "--cached", "README.md")

    commit = checkout.commit("Remove the readme", [Path("README.md")])

    assert checkout.run("ls-tree", "--name-only", commit) == ""


def test_a_commit_of_a_removed_directory_removes_its_files(
    checkout: GitCommandRunner,
):
    directory = checkout.working_directory / "plugin"
    directory.mkdir()
    (directory / "first.txt").write_text("first\n")
    (directory / "second.txt").write_text("second\n")
    checkout.commit("Add the plugin", [Path("plugin")])
    for file in directory.iterdir():
        file.unlink()
    directory.rmdir()

    commit = checkout.commit("Remove the plugin", [Path("plugin")])

    assert checkout.run("ls-tree", "--name-only", commit) == "README.md"


# %% finding the checkout


def test_a_directory_inside_a_checkout_finds_the_checkout_s_root(
    checkout: GitCommandRunner,
):
    inside = checkout.working_directory / "nested"
    inside.mkdir()

    assert GitCommandRunner.enclosing(inside) == checkout


def test_a_directory_outside_every_checkout_finds_none(tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()

    assert GitCommandRunner.enclosing(outside) is None


# %% identity


def test_the_identity_variables_take_precedence_over_the_configuration(
    checkout: GitCommandRunner, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv(GitIdentityVariable.AUTHOR_NAME, "Environment Author")
    monkeypatch.setenv(GitIdentityVariable.AUTHOR_EMAIL, "environment@example.com")

    author = checkout.identity(GitIdentity.AUTHOR)

    assert author.startswith("Environment Author <environment@example.com>")


# %% cloning


@pytest.fixture
def hosted(checkout: GitCommandRunner, tmp_path: Path) -> Repository:
    """:return: A repository whose ``main`` is the checkout's, kept as a bare
    repository under ``hosting`` the way GitHub keeps it."""
    repository = Repository("an-owner", "a-repository")
    bare = tmp_path / "hosting" / repository.owner / f"{repository.name}.git"
    checkout.run("init", "--quiet", "--bare", "--initial-branch=main", str(bare))
    checkout.run("push", "--quiet", str(bare), "HEAD:refs/heads/main")
    return repository


def test_a_clone_holds_the_repository_s_commits(
    checkout: GitCommandRunner, hosted: Repository, tmp_path: Path
):
    url = hosted.clone_url_under(f"file://{tmp_path / 'hosting'}")

    clone = GitCommandRunner.clone(url, tmp_path / "clones" / hosted.name)

    assert clone.commit_at("HEAD") == checkout.commit_at("HEAD")


def test_a_clone_s_origin_is_the_repository_cloned(hosted: Repository, tmp_path: Path):
    url = hosted.clone_url_under(f"file://{tmp_path / 'hosting'}")

    clone = GitCommandRunner.clone(url, tmp_path / "clones" / hosted.name)

    [origin] = clone.remotes()
    assert (origin.name, origin.repository) == (RemoteName.ORIGIN, hosted)


def test_a_relative_destination_is_cloned_where_it_names(
    checkout: GitCommandRunner,
    hosted: Repository,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = hosted.clone_url_under(f"file://{tmp_path / 'hosting'}")
    monkeypatch.chdir(tmp_path)

    GitCommandRunner.clone(url, Path("clones") / hosted.name)

    assert GitCommandRunner(tmp_path / "clones" / hosted.name).commit_at(
        "HEAD"
    ) == checkout.commit_at("HEAD")


def test_cloning_into_a_non_empty_directory_is_refused(
    hosted: Repository, tmp_path: Path
):
    url = hosted.clone_url_under(f"file://{tmp_path / 'hosting'}")
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "file.txt").write_text("in the way\n")

    with pytest.raises(GitCommandFailed):
        GitCommandRunner.clone(url, occupied)


# %% remote branch tips


def test_a_remote_branch_s_tip_is_the_commit_pushed(
    checkout: GitCommandRunner, published: RemoteBranch
):
    assert checkout.remote_branch_tip(published) == checkout.commit_at("HEAD")


def test_a_branch_the_remote_lacks_has_no_tip(
    checkout: GitCommandRunner, published: RemoteBranch
):
    assert (
        checkout.remote_branch_tip(RemoteBranch(published.remote, "elsewhere")) is None
    )


# %% running git unattended


def test_git_never_prompts_on_the_terminal(tmp_path: Path) -> None:
    git = GitCommandRunner(tmp_path)

    prompt = git.run(
        "-c",
        f"alias.prompt=!printenv {GitVariable.TERMINAL_PROMPT}",
        "prompt",
    )

    assert (
        prompt == GitCommandRunner.unattended_environment[GitVariable.TERMINAL_PROMPT]
    )


# %% what a push changes


def test_a_pre_push_line_reads_as_the_update_it_describes():
    pushed, published = "1" * 40, "2" * 40
    line = f"refs/heads/work {pushed} refs/heads/main {published}"

    update = ReferenceUpdate.from_line(line)

    assert update == ReferenceUpdate(
        "refs/heads/work", pushed, "refs/heads/main", published
    )


def test_a_pre_push_line_missing_a_field_is_refused():
    with pytest.raises(MalformedReferenceUpdateError):
        ReferenceUpdate.from_line(f"refs/heads/work {'1' * 40} refs/heads/main")
