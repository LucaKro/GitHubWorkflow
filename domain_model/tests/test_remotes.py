"""
Tests for :mod:`domain_model.git.remotes`: a checkout's remotes, their branches as the
remote has them and as last fetched, and every push.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from domain_model.git.commands import GitCommandRunner
from domain_model.git.exceptions import MalformedReferenceUpdateError
from domain_model.git.remotes import (
    ProposedPush,
    ReferenceUpdate,
    Remote,
    RemoteBranch,
    RemoteName,
    UnconfiguredRemote,
)
from domain_model.git.revisions import BranchName, BranchTip, CommitHash, LocalBranch
from domain_model.git.working_tree import WorkingTree
from domain_model.repository import Repository

from .git_checkouts import checkout, head, published  # noqa: F401

# %% remotes


def test_a_remote_names_the_repository_it_pushes_to(
    checkout: GitCommandRunner,  # noqa: F811
) -> None:
    checkout.run(
        "remote", "add", "origin", "https://github.com/an-owner/a-repository.git"
    )

    [remote] = Remote.read_configured(checkout)

    assert remote.repository == Repository("an-owner", "a-repository")


def test_a_remote_that_names_no_repository_has_none(
    checkout: GitCommandRunner,  # noqa: F811
) -> None:
    checkout.run("remote", "add", "local", "/a/plain/path")

    assert Remote.read_configured(checkout)[0].repository is None


def test_a_remote_s_branch_is_the_branch_of_that_name_on_it(
    checkout: GitCommandRunner,  # noqa: F811
) -> None:
    remote = Remote.from_push_url(checkout, "fork", "/a/plain/path")

    assert remote.branch(BranchName("feature")) == RemoteBranch(
        remote, BranchName("feature")
    )


@pytest.fixture
def cloned(checkout: GitCommandRunner, tmp_path: Path) -> Remote:  # noqa: F811
    """:return: ``origin`` of a clone of a bare repository whose default branch is
    ``trunk``."""
    bare = tmp_path / "trunk.git"
    checkout.run("init", "--quiet", "--bare", "--initial-branch=trunk", str(bare))
    checkout.run("push", "--quiet", str(bare), "HEAD:refs/heads/trunk")
    [origin] = Remote.read_configured(
        GitCommandRunner.clone(str(bare), tmp_path / "clone")
    )
    return origin


def test_a_remote_s_default_branch_is_the_one_its_head_names(cloned: Remote) -> None:
    assert cloned.default_branch() == cloned.branch(BranchName("trunk"))


def test_an_unreachable_remote_s_default_branch_is_the_one_last_fetched(
    cloned: Remote, tmp_path: Path
) -> None:
    cloned.git.run("remote", "set-url", cloned.name, str(tmp_path / "gone.git"))

    assert cloned.default_branch() == cloned.branch(BranchName("trunk"))


def test_an_unreachable_remote_never_fetched_has_no_known_default_branch(
    checkout: GitCommandRunner, tmp_path: Path  # noqa: F811
) -> None:
    checkout.run("remote", "add", RemoteName.ORIGIN, str(tmp_path / "gone.git"))
    [origin] = Remote.read_configured(checkout)

    assert origin.default_branch() is None


def test_every_branch_of_a_remote_is_listed_with_its_tip(
    checkout: GitCommandRunner, published: RemoteBranch  # noqa: F811
) -> None:
    first = head(checkout)
    checkout.run("commit", "--quiet", "--allow-empty", "--message", "Move on")
    checkout.run("push", "--quiet", RemoteName.ORIGIN, "HEAD:refs/heads/a/nested")

    assert published.remote.branch_tips() == [
        BranchTip(BranchName("a/nested"), CommitHash(head(checkout))),
        BranchTip(published.name, CommitHash(first)),
    ]


def test_branches_still_at_their_commits_are_deleted_in_one_push(
    checkout: GitCommandRunner, published: RemoteBranch  # noqa: F811
) -> None:
    others = [published.remote.branch(BranchName(name)) for name in ("second", "third")]
    checkout.run(
        "push",
        "--quiet",
        RemoteName.ORIGIN,
        *[f"HEAD:{branch.reference}" for branch in others],
    )
    commit = CommitHash(head(checkout))

    refused = published.remote.delete_branches(
        [BranchTip(branch.name, commit) for branch in [published, *others]]
    )

    assert (refused, [branch.exists() for branch in [published, *others]]) == (
        [],
        [False, False, False],
    )


def test_a_branch_that_moved_is_kept_and_named(
    checkout: GitCommandRunner, published: RemoteBranch  # noqa: F811
) -> None:
    before = CommitHash(head(checkout))
    checkout.run("commit", "--quiet", "--allow-empty", "--message", "Move on")
    checkout.run("push", "--quiet", RemoteName.ORIGIN, f"HEAD:{published.reference}")

    refused = published.remote.delete_branches([BranchTip(published.name, before)])

    assert (refused, published.exists()) == ([published.name], True)


# %% a branch on a remote


def test_a_pushed_branch_is_on_its_remote(
    published: RemoteBranch,  # noqa: F811
) -> None:
    assert published.exists()


def test_a_branch_never_pushed_is_not_on_the_remote(
    published: RemoteBranch,  # noqa: F811
) -> None:
    assert not published.remote.branch(BranchName("elsewhere")).exists()


def test_a_remote_branch_s_tip_is_the_commit_pushed(
    checkout: GitCommandRunner, published: RemoteBranch  # noqa: F811
) -> None:
    assert published.tip() == head(checkout)


def test_a_branch_only_ending_in_another_s_reference_is_not_its_tip(
    published: RemoteBranch,  # noqa: F811
) -> None:
    absent = published.remote.branch(BranchName("absent"))
    published.remote.git.run(
        "push", "--quiet", RemoteName.ORIGIN, f"HEAD:refs/heads/a/{absent.reference}"
    )

    assert absent.tip() is None


def test_a_deleted_branch_is_gone_from_its_remote(
    published: RemoteBranch,  # noqa: F811
) -> None:
    deleted = published.delete()

    assert (deleted.succeeded, published.exists()) == (True, False)


def test_a_fetched_branch_moves_only_its_remote_tracking_branch(
    checkout: GitCommandRunner, published: RemoteBranch  # noqa: F811
) -> None:
    published.fetch()

    assert published.tracking_branch.commit().hash == head(checkout)


def test_a_branch_is_fetched_from_a_url_into_its_remote_s_tracking_branch(
    checkout: GitCommandRunner, published: RemoteBranch, tmp_path: Path  # noqa: F811
) -> None:
    url = str(tmp_path / "remote.git")
    elsewhere = UnconfiguredRemote(checkout, "elsewhere", url, None).branch(
        published.name
    )

    elsewhere.fetch().raise_if_failed()

    assert elsewhere.tracking_branch.commit().hash == head(checkout)


def test_a_branch_never_fetched_resolves_to_no_commit(
    published: RemoteBranch,  # noqa: F811
) -> None:
    assert (
        published.remote.branch(
            BranchName("elsewhere")
        ).tracking_branch.commit_or_none()
        is None
    )


def test_a_pushed_branch_s_remote_tracking_branch_was_written_from_its_remote(
    published: RemoteBranch,  # noqa: F811
) -> None:
    assert published.tracking_branch.was_fetched_or_pushed()


def test_a_branch_never_fetched_or_pushed_was_not(
    published: RemoteBranch,  # noqa: F811
) -> None:
    elsewhere = published.remote.branch(BranchName("elsewhere"))

    assert not elsewhere.tracking_branch.was_fetched_or_pushed()


def test_a_forgotten_remote_tracking_branch_resolves_to_no_commit(
    published: RemoteBranch,  # noqa: F811
) -> None:
    published.tracking_branch.delete()

    assert published.tracking_branch.commit_or_none() is None


# %% pushing


def upstream(git: GitCommandRunner, branch: str) -> str | None:
    """
    :param git: The checkout.
    :param branch: A local branch.
    :return: The branch it tracks, ``None`` when it tracks none.
    """
    found = git.attempt("rev-parse", "--abbrev-ref", f"{branch}@{{upstream}}")
    return found.output if found.succeeded else None


def test_a_push_that_sets_the_upstream_makes_the_branch_track_where_it_went(
    checkout: GitCommandRunner, published: RemoteBranch  # noqa: F811
) -> None:
    local = LocalBranch(checkout, BranchName("feature"))
    local.create(LocalBranch(checkout, BranchName("main")))
    pushed = published.remote.branch(BranchName("feature"))

    ProposedPush(pushed, local, sets_upstream=True).publish()

    assert upstream(checkout, "feature") == f"{pushed.remote.name}/{pushed.name}"


def test_a_plain_push_leaves_the_branch_tracking_none(
    checkout: GitCommandRunner, published: RemoteBranch  # noqa: F811
) -> None:
    local = LocalBranch(checkout, BranchName("feature"))
    local.create(LocalBranch(checkout, BranchName("main")))

    ProposedPush(published.remote.branch(BranchName("feature")), local).publish()

    assert upstream(checkout, "feature") is None


def test_a_pushed_commit_is_the_branch_s_tip(
    checkout: GitCommandRunner, published: RemoteBranch  # noqa: F811
) -> None:
    checkout.run("commit", "--quiet", "--allow-empty", "--message", "Move on")

    ProposedPush(published, WorkingTree(checkout).head()).publish().raise_if_failed()

    assert published.tip() == head(checkout)


def test_a_push_skipping_the_hook_is_not_refused_by_it(
    checkout: GitCommandRunner, published: RemoteBranch  # noqa: F811
) -> None:
    hook = checkout.git_path(Path("hooks/pre-push"))
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)
    pushed = published.remote.branch(BranchName("feature"))
    source = WorkingTree(checkout).head()

    refused = ProposedPush(pushed, source).publish()
    skipped = ProposedPush(pushed, source, runs_push_hook=False).publish()

    assert (refused.succeeded, skipped.succeeded) == (False, True)


# %% what a push changes


def test_a_pre_push_line_reads_as_the_update_it_describes() -> None:
    pushed, published = "1" * 40, "2" * 40
    line = f"refs/heads/work {pushed} refs/heads/main {published}"

    update = ReferenceUpdate.from_line(line)

    assert update == ReferenceUpdate(
        "refs/heads/work", CommitHash(pushed), "refs/heads/main", CommitHash(published)
    )


def test_a_pre_push_line_missing_a_field_is_refused() -> None:
    with pytest.raises(MalformedReferenceUpdateError):
        ReferenceUpdate.from_line(f"refs/heads/work {'1' * 40} refs/heads/main")
