"""
Scratch checkouts the git tests run in: one with a commit on ``main``, and the same with
``main`` pushed to a bare ``origin``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from domain_model.git.commands import GitCommandRunner
from domain_model.git.remotes import Remote, RemoteBranch, RemoteName

# %% a checkout


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


def head(git: GitCommandRunner) -> str:
    """:param git: A checkout.
    :return: The commit it has checked out."""
    return git.run("rev-parse", "HEAD")


# %% a remote


@pytest.fixture
def published(checkout: GitCommandRunner, tmp_path: Path) -> RemoteBranch:
    """:return: ``main``, pushed to a bare ``origin`` of the checkout."""
    bare = tmp_path / "remote.git"
    checkout.run("init", "--quiet", "--bare", str(bare))
    checkout.run("remote", "add", RemoteName.ORIGIN, str(bare))
    branch = Remote(checkout, RemoteName.ORIGIN, str(bare), None).branch("main")
    checkout.run("push", "--quiet", RemoteName.ORIGIN, f"HEAD:{branch.reference}")
    return branch
