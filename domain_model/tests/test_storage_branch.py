"""
Tests for :class:`basstler_domain_model.git.storage_branch.StorageBranch`: a branch read
and written without a checkout, by several writers.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from basstler_domain_model.git.commands import (
    GitCommandResult,
    GitCommandRunner,
    RemoteBranch,
    RemoteName,
)
from basstler_domain_model.git.exceptions import StorageBranchWriteConflict
from basstler_domain_model.git.storage_branch import StorageBranch

# %% fixtures


@pytest.fixture
def remote(tmp_path: Path) -> Path:
    """:return: A bare repository holding one commit on ``main``."""
    bare = tmp_path / "remote.git"
    GitCommandRunner(tmp_path).run(
        "init", "--quiet", "--bare", "--initial-branch=main", str(bare)
    )
    seed = GitCommandRunner(tmp_path / "seed")
    seed.working_directory.mkdir()
    seed.run("init", "--quiet", "--initial-branch=main")
    identify(seed)
    seed.run("commit", "--quiet", "--allow-empty", "--message", "Start")
    seed.run("push", "--quiet", str(bare), "HEAD:refs/heads/main")
    return bare


def identify(git: GitCommandRunner) -> None:
    """:param git: A checkout to commit in."""
    git.run("config", "user.name", "Test Author")
    git.run("config", "user.email", "test.author@example.com")


def storage(remote: Path, tmp_path: Path, name: str) -> StorageBranch:
    """
    :param remote: The bare repository.
    :param tmp_path: Where to clone it.
    :param name: The clone's directory name.
    :return: The storage branch, as that clone uses it.
    """
    git = GitCommandRunner(tmp_path)
    git.run("clone", "--quiet", str(remote), name)
    clone = GitCommandRunner(tmp_path / name)
    identify(clone)
    return StorageBranch(clone, RemoteBranch(RemoteName.ORIGIN, "storage"))


# %% reading and writing


def test_before_the_first_write_there_is_nothing_to_read(remote, tmp_path):
    branch = storage(remote, tmp_path, "reader")

    assert branch.fetch() is False
    assert branch.read(Path("file.md")) is None


def test_the_first_write_creates_the_branch_with_the_file(remote, tmp_path):
    storage(remote, tmp_path, "writer").write({Path("file.md"): "text\n"}, "Write")
    reader = storage(remote, tmp_path, "reader")

    assert reader.fetch() is True
    assert reader.read(Path("file.md")) == "text\n"


def test_a_write_leaves_the_files_it_does_not_write_alone(remote, tmp_path):
    branch = storage(remote, tmp_path, "writer")
    branch.write({Path("one.md"): "one\n"}, "Write")

    branch.write({Path("two.md"): "two\n"}, "Write")

    assert branch.read(Path("one.md")) == "one\n"
    assert branch.read(Path("two.md")) == "two\n"


def test_a_writer_behind_another_keeps_both_writes(remote, tmp_path):
    """
    The later writer fetched before the earlier one wrote, so its first push is refused
    and it builds again on the new tip.
    """
    first = storage(remote, tmp_path, "first")
    second = storage(remote, tmp_path, "second")
    first.write({Path("one.md"): "one\n"}, "Write")
    second.fetch()
    first.write({Path("two.md"): "two\n"}, "Write")

    second.write({Path("three.md"): "three\n"}, "Write")

    assert second.read(Path("two.md")) == "two\n"
    assert second.read(Path("three.md")) == "three\n"


def test_a_file_is_read_back_exactly_as_written(remote: Path, tmp_path: Path) -> None:
    text = "line\n\n  "
    branch = storage(remote, tmp_path, "writer")

    branch.write({Path("file.md"): text}, "Write")

    assert branch.read(Path("file.md")) == text


def test_a_writer_behind_another_on_the_same_file_is_refused(
    remote: Path, tmp_path: Path
) -> None:
    first = storage(remote, tmp_path, "first")
    second = storage(remote, tmp_path, "second")
    first.write({Path("one.md"): "one\n"}, "Write")
    second.fetch()
    first.write({Path("one.md"): "changed\n"}, "Write")

    with pytest.raises(StorageBranchWriteConflict):
        second.write({Path("one.md"): "overwritten\n"}, "Write")


def test_a_write_leaves_the_checkout_untouched(remote, tmp_path):
    branch = storage(remote, tmp_path, "writer")
    before = branch.git.run("status", "--porcelain"), branch.git.run(
        "rev-parse", "HEAD"
    )

    branch.write({Path("file.md"): "text\n"}, "Write")

    assert (
        branch.git.run("status", "--porcelain"),
        branch.git.run("rev-parse", "HEAD"),
    ) == before


@dataclass(frozen=True)
class GitCallsRecorded(GitCommandRunner):
    """
    Runs git, keeping the subcommand of every call.
    """

    subcommands: list[str] = field(default_factory=list)
    """
    The subcommand of every call, in order.
    """

    def attempt(
        self, *arguments: str, environment: Mapping[str, str] | None = None
    ) -> GitCommandResult:
        self.subcommands.append(arguments[0])
        return super().attempt(*arguments, environment=environment)


def test_a_branch_that_did_not_move_is_not_fetched_again(remote, tmp_path):
    storage(remote, tmp_path, "writer").write({Path("file.md"): "text\n"}, "Write")
    reader = storage(remote, tmp_path, "reader")
    reader.fetch()
    recorded = GitCallsRecorded(reader.git.working_directory)

    assert StorageBranch(recorded, reader.branch).fetch() is True
    assert "fetch" not in recorded.subcommands
