"""
Tests for :mod:`domain_model.git.commands`: running git in a checkout, finding and
cloning one, and what it records about the person committing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from domain_model.environment import GitIdentityVariable, GitVariable
from domain_model.git.commands import GitCommandRunner, GitIdentity
from domain_model.git.exceptions import GitCommandFailed
from domain_model.git.remotes import Remote, RemoteName
from domain_model.locations import GitStateFile
from domain_model.repository import Repository

from .git_checkouts import checkout, head  # noqa: F401

# %% running git


def test_a_git_result_keeps_the_command_as_invoked(
    checkout: GitCommandRunner,  # noqa: F811
) -> None:
    assert checkout.attempt("version").arguments == ("git", "version")


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


def test_a_git_directory_file_is_found_inside_the_checkout_s_git_directory(
    checkout: GitCommandRunner,  # noqa: F811
) -> None:
    assert checkout.git_path(GitStateFile.MERGE_MESSAGE) == (
        checkout.working_directory / ".git" / GitStateFile.MERGE_MESSAGE
    )


# %% finding the checkout


def test_a_directory_inside_a_checkout_finds_the_checkout_s_root(
    checkout: GitCommandRunner,  # noqa: F811
) -> None:
    inside = checkout.working_directory / "nested"
    inside.mkdir()

    assert GitCommandRunner.enclosing(inside) == checkout


def test_a_directory_outside_every_checkout_finds_none(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()

    assert GitCommandRunner.enclosing(outside) is None


# %% identity


def test_the_identity_variables_take_precedence_over_the_configuration(
    checkout: GitCommandRunner, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    monkeypatch.setenv(GitIdentityVariable.AUTHOR_NAME, "Environment Author")
    monkeypatch.setenv(GitIdentityVariable.AUTHOR_EMAIL, "environment@example.com")

    author = checkout.identity(GitIdentity.AUTHOR)

    assert author.startswith("Environment Author <environment@example.com>")


# %% cloning


@pytest.fixture
def hosted(checkout: GitCommandRunner, tmp_path: Path) -> Repository:  # noqa: F811
    """:return: A repository whose ``main`` is the checkout's, kept as a bare
    repository under ``hosting`` the way GitHub keeps it."""
    repository = Repository("an-owner", "a-repository")
    bare = tmp_path / "hosting" / repository.owner / f"{repository.name}.git"
    checkout.run("init", "--quiet", "--bare", "--initial-branch=main", str(bare))
    checkout.run("push", "--quiet", str(bare), "HEAD:refs/heads/main")
    return repository


def test_a_clone_holds_the_repository_s_commits(
    checkout: GitCommandRunner, hosted: Repository, tmp_path: Path  # noqa: F811
) -> None:
    url = hosted.rooted_clone_url(f"file://{tmp_path / 'hosting'}")

    clone = GitCommandRunner.clone(url, tmp_path / "clones" / hosted.name)

    assert head(clone) == head(checkout)


def test_a_clone_s_origin_is_the_repository_cloned(
    hosted: Repository, tmp_path: Path
) -> None:
    url = hosted.rooted_clone_url(f"file://{tmp_path / 'hosting'}")

    clone = GitCommandRunner.clone(url, tmp_path / "clones" / hosted.name)

    [origin] = Remote.configured(clone)
    assert (origin.name, origin.repository) == (RemoteName.ORIGIN, hosted)


def test_a_relative_destination_is_cloned_where_it_names(
    checkout: GitCommandRunner,  # noqa: F811
    hosted: Repository,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = hosted.rooted_clone_url(f"file://{tmp_path / 'hosting'}")
    monkeypatch.chdir(tmp_path)

    GitCommandRunner.clone(url, Path("clones") / hosted.name)

    assert head(GitCommandRunner(tmp_path / "clones" / hosted.name)) == head(checkout)


def test_cloning_into_a_non_empty_directory_is_refused(
    hosted: Repository, tmp_path: Path
) -> None:
    url = hosted.rooted_clone_url(f"file://{tmp_path / 'hosting'}")
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "file.txt").write_text("in the way\n")

    with pytest.raises(GitCommandFailed):
        GitCommandRunner.clone(url, occupied)
