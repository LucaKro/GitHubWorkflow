"""
The repositories on GitHub the tests' stand-ins name, never reached.
"""

from __future__ import annotations

from dataclasses import dataclass

from domain_model.class_property import classproperty
from domain_model.repository import Repository

from github_workflow.settings import WorkflowSettings

from .repositories_by_owner import RepositoriesByOwner

# %% the repositories


@dataclass(frozen=True)
class ScratchGitHub:
    """
    The owner's repository and the one it was forked from, as the stand-ins name them.
    """

    @classproperty
    def owned(cls) -> Repository:
        """
        The owner's repository, a fork.
        """
        return Repository(WorkflowSettings().owner, RepositoriesByOwner.repository_name)

    @classproperty
    def upstream(cls) -> Repository:
        """
        The repository the owner's was forked from.
        """
        return Repository("an-upstream-owner", RepositoriesByOwner.repository_name)
