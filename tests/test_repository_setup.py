"""
Tests for :mod:`github_workflow.repository_setup`: the features the workflow relies on
are never turned on by the workflow; where one is off, a line says where the person
turns it on.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from basstler_domain_model.github.repository_client import (
    RepositoryDiscussions,
    RepositorySettings,
)
from basstler_domain_model.repository import Repository

from github_workflow.hooks import Tone
from github_workflow.repository_setup import RepositorySetup

REPOSITORY = Repository("LucaKro", "a-repository")
"""
The repository every setup here is made sure of.
"""

# %% settings in memory


@dataclass(frozen=True)
class SettingsInMemory(RepositorySettings, RepositoryDiscussions):
    """
    A repository's features, each on or off, recording every change asked for.
    """

    deletes: bool = True
    """
    Whether merged branches are deleted.
    """

    issues: bool = True
    """
    Whether issues are on.
    """

    actions: bool | None = True
    """
    Whether Actions may run, ``None`` when that cannot be read.
    """

    discussions: bool = True
    """
    Whether Discussions are on.
    """

    changes: list[str] = field(default_factory=list)
    """
    Every change asked for.
    """

    def deletes_merged_branches(self) -> bool:
        return self.deletes

    def turn_on_merged_branch_deletion(self) -> bool:
        self.changes.append("deletion")
        return True

    def issues_enabled(self) -> bool:
        return self.issues

    def turn_on_issues(self) -> bool:
        self.changes.append("issues")
        return True

    def actions_enabled(self) -> bool | None:
        return self.actions

    def discussions_enabled(self) -> bool:
        return self.discussions

    def turn_on_actions(self) -> bool:
        self.changes.append("actions")
        return True


# %% turning features on


def test_a_repository_set_up_already_is_left_alone():
    settings = SettingsInMemory()

    assert RepositorySetup(REPOSITORY, settings, settings).lines() == []
    assert settings.changes == []


def test_merged_branch_deletion_and_issues_that_are_off_are_left_for_the_person():
    """
    Turning a feature on changes the repository for everyone who uses it, a fork's
    public issues among it: only the person opts in.
    """
    settings = SettingsInMemory(deletes=False, issues=False)

    lines = RepositorySetup(REPOSITORY, settings, settings).lines()

    assert settings.changes == []
    assert [line.tone for line in lines] == [Tone.ACTION] * 2


def test_actions_that_are_off_are_left_for_the_person_to_turn_on():
    """
    Actions run every workflow on the repository, an upstream's on a fork among them,
    under the owner's account: only the person decides that.
    """
    settings = SettingsInMemory(actions=False)

    [line] = RepositorySetup(REPOSITORY, settings, settings).lines()

    assert settings.changes == []
    assert line.tone is Tone.ACTION
    assert f"{REPOSITORY.settings_url}/actions" in line.text


def test_actions_that_cannot_be_read_are_not_touched():
    settings = SettingsInMemory(actions=None)

    assert RepositorySetup(REPOSITORY, settings, settings).lines() == []
    assert settings.changes == []


@pytest.mark.parametrize(
    "settings, page",
    [
        (SettingsInMemory(deletes=False), REPOSITORY.settings_url),
        (SettingsInMemory(issues=False), REPOSITORY.settings_url),
        (SettingsInMemory(actions=False), f"{REPOSITORY.settings_url}/actions"),
        (SettingsInMemory(discussions=False), REPOSITORY.settings_url),
    ],
    ids=["deletion", "issues", "actions", "discussions"],
)
def test_a_feature_that_is_off_says_where_to_turn_it_on(
    settings: SettingsInMemory, page: str
):
    [line] = RepositorySetup(REPOSITORY, settings, settings).lines()

    assert settings.changes == []
    assert line.tone is Tone.ACTION
    assert page in line.text
