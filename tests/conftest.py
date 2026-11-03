"""
Fixtures shared by every test: scratch repositories laid out by owner, standing in for
GitHub accounts, committed to under their configured identity.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from basstler_domain_model.environment import ClaudeCodeVariable, GitIdentityVariable

from github_workflow.settings import WorkflowSettings

from .repositories_by_owner import RepositoriesByOwner

# %% identity


@pytest.fixture(autouse=True)
def configured_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Clears the identity variables the environment may set, so every commit is made under
    the identity its checkout configures.
    """
    for variable in GitIdentityVariable:
        monkeypatch.delenv(variable, raising=False)


@pytest.fixture(autouse=True)
def outside_claude_code(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Clears the variable marking a command Claude Code runs, so a push is a person's
    unless the test marks it as a Claude Code session's.
    """
    monkeypatch.delenv(ClaudeCodeVariable.COMMAND_MARKER, raising=False)


# %% repositories


@pytest.fixture
def settings() -> WorkflowSettings:
    """:return: The workflow's own settings, whose owner counts as mine."""
    return WorkflowSettings()


@pytest.fixture
def repositories(tmp_path: Path) -> RepositoriesByOwner:
    """:return: An empty place for bare repositories and clones."""
    return RepositoriesByOwner(tmp_path)


@pytest.fixture
def owned_url(repositories: RepositoriesByOwner, settings: WorkflowSettings) -> str:
    """:return: The URL of a repository of the owner's."""
    return repositories.create(settings.owner)


@pytest.fixture
def foreign_url(repositories: RepositoriesByOwner) -> str:
    """:return: The URL of a repository of somebody else's."""
    return repositories.create(RepositoriesByOwner.foreign_owner)
