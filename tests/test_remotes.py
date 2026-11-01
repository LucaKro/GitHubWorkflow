"""
Tests for :mod:`github_workflow.remotes`: writes go only to the owner's repositories.
"""

from __future__ import annotations

import pytest

from github_workflow.exceptions import AmbiguousOwnedRemoteError, NoOwnedRemoteError
from basstler_domain_model.git.commands import RemoteName

from github_workflow.remotes import OwnedRemotes
from github_workflow.settings import WorkflowSettings

from .repositories_by_owner import RepositoriesByOwner

# %% choosing the remote


def test_an_owned_origin_is_chosen(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
):
    checkout = repositories.clone(owned_url, "mine")

    chosen = OwnedRemotes.read(checkout.git, settings).chosen

    assert chosen.name == RemoteName.ORIGIN
    assert chosen.repository.owner == settings.owner


def test_in_a_clone_of_the_upstream_the_owner_s_fork_is_chosen(
    repositories: RepositoriesByOwner,
    owned_url: str,
    foreign_url: str,
    settings: WorkflowSettings,
):
    checkout = repositories.clone(foreign_url, "upstream-clone")
    checkout.git.run("remote", "add", "fork", owned_url)

    assert OwnedRemotes.read(checkout.git, settings).chosen.name == "fork"


def test_a_clone_of_somebody_else_s_repository_has_nothing_to_write_to(
    repositories: RepositoriesByOwner, foreign_url: str, settings: WorkflowSettings
):
    checkout = repositories.clone(foreign_url, "theirs")

    with pytest.raises(NoOwnedRemoteError):
        OwnedRemotes.read(checkout.git, settings).chosen


def test_two_owned_remotes_without_origin_are_not_guessed_between(
    repositories: RepositoriesByOwner, foreign_url: str, settings: WorkflowSettings
):
    checkout = repositories.clone(foreign_url, "upstream-clone")
    checkout.git.run(
        "remote", "add", "first", repositories.create(settings.owner, "one")
    )
    checkout.git.run(
        "remote", "add", "second", repositories.create(settings.owner, "two")
    )

    with pytest.raises(AmbiguousOwnedRemoteError):
        OwnedRemotes.read(checkout.git, settings).chosen
