"""
Tests for :class:`github_workflow.plugin.Distribution`: the names the workflow's
distributions are installed under are the names its project declares.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from domain_model.python_project import ProjectKey, Pyproject

import github_workflow
from github_workflow.plugin import Distribution

# %% the names the project declares


@pytest.fixture
def workflow_project() -> dict[str, Any]:
    """:return: The ``[project]`` table of the plugin's own ``pyproject.toml``."""
    plugin = Path(github_workflow.__file__).parents[2]
    return Pyproject(plugin).settings()[ProjectKey.PROJECT]


def test_the_workflow_depends_on_the_domain_model_by_the_name_it_installs_under(
    workflow_project: dict[str, Any],
) -> None:
    assert Distribution.DOMAIN_MODEL in workflow_project[ProjectKey.DEPENDENCIES]


def test_the_workflow_declares_the_name_it_installs_under(
    workflow_project: dict[str, Any],
) -> None:
    assert workflow_project[ProjectKey.NAME] == Distribution.WORKFLOW
