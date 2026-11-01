"""
Fixtures shared by every test: scratch repositories laid out by owner, standing in for
GitHub accounts.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from github_workflow.settings import WorkflowSettings

from .repositories_by_owner import RepositoriesByOwner

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
