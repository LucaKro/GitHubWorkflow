"""
The choices a person makes once for the whole workflow.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from github_workflow.plugin import Distribution, ToolRepository

if TYPE_CHECKING:
    from basstler_domain_model.repository import Repository

# %% settings


@dataclass(frozen=True)
class WorkflowSettings:
    """
    Whose repositories the workflow writes to, and where it keeps its notes in them.
    """

    owner: str = ToolRepository.WORKFLOW.owner
    """
    The GitHub account whose repositories alone are written to, by default the one the
    workflow's own repository belongs to.
    """

    notes_branch: str = f"{Distribution.WORKFLOW}/notes"
    """
    The branch the notes and progress live on, in every repository.
    """

    def owns(self, repository: Repository) -> bool:
        """
        :param repository: A GitHub repository.
        :return: Whether it belongs to :attr:`owner`, whose name GitHub matches in any
            case.
        """
        return repository.owner.casefold() == self.owner.casefold()
