"""
Tests for :mod:`github_workflow.remotes`: writes go only to the owner's repositories.
"""

from __future__ import annotations

import pytest
from domain_model.git.commands import RemoteName

from github_workflow.exceptions import AmbiguousOwnedRemoteError, NoOwnedRemoteError
from github_workflow.remotes import OwnedRemotes
from github_workflow.settings import WorkflowSettings

from .repositories_by_owner import RepositoriesByOwner

# %% choosing the remote


def test_an_owned_origin_is_chosen(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
) -> None:
    checkout = repositories.clone(owned_url, "mine")

    chosen = OwnedRemotes.read(checkout.git, settings).chosen

    assert chosen.name == RemoteName.ORIGIN
    assert chosen.repository.owner == settings.owner


def test_in_a_clone_of_the_upstream_the_owner_s_fork_is_chosen(
    repositories: RepositoriesByOwner,
    owned_url: str,
    foreign_url: str,
    settings: WorkflowSettings,
) -> None:
    checkout = repositories.clone(foreign_url, "upstream-clone")
    checkout.git.run("remote", "add", "fork", owned_url)

    assert OwnedRemotes.read(checkout.git, settings).chosen.name == "fork"


def test_a_clone_of_somebody_else_s_repository_has_nothing_to_write_to(
    repositories: RepositoriesByOwner, foreign_url: str, settings: WorkflowSettings
) -> None:
    checkout = repositories.clone(foreign_url, "theirs")

    with pytest.raises(NoOwnedRemoteError):
        OwnedRemotes.read(checkout.git, settings).chosen


def test_two_owned_remotes_without_origin_are_not_guessed_between(
    repositories: RepositoriesByOwner, foreign_url: str, settings: WorkflowSettings
) -> None:
    checkout = repositories.clone(foreign_url, "upstream-clone")
    checkout.git.run(
        "remote", "add", "first", repositories.create(settings.owner, "one")
    )
    checkout.git.run(
        "remote", "add", "second", repositories.create(settings.owner, "two")
    )

    with pytest.raises(AmbiguousOwnedRemoteError):
        OwnedRemotes.read(checkout.git, settings).chosen


# %% hosts


@pytest.mark.parametrize(
    "path",
    [
        "https://gitlab.com/{owner}/anything.git",
        "git@evil.example:{owner}/anything.git",
        "https://example.com/mirror/{owner}/anything.git",
    ],
)
def test_a_remote_off_github_is_not_owned_whatever_its_path(
    repositories: RepositoriesByOwner,
    owned_url: str,
    settings: WorkflowSettings,
    path: str,
) -> None:
    checkout = repositories.clone(owned_url, "mine")
    checkout.git.run("remote", "add", "elsewhere", path.format(owner=settings.owner))

    owned = OwnedRemotes.read(checkout.git, settings).owned

    assert [remote.name for remote in owned] == [RemoteName.ORIGIN]


@pytest.mark.parametrize(
    "path",
    [
        "https://github.com/{owner}/anything.git",
        "git@github.com:{owner}/anything.git",
        "http://local_proxy@127.0.0.1:41729/git/{owner}/anything",
    ],
)
def test_a_remote_on_github_or_the_cloud_proxy_is_owned(
    repositories: RepositoriesByOwner,
    foreign_url: str,
    settings: WorkflowSettings,
    path: str,
) -> None:
    checkout = repositories.clone(foreign_url, "theirs")
    checkout.git.run("remote", "add", "fork", path.format(owner=settings.owner))

    assert OwnedRemotes.read(checkout.git, settings).chosen.name == "fork"
