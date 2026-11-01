"""
The choices a person makes once for the whole workflow.
"""

from __future__ import annotations

from dataclasses import dataclass

from basstler_domain_model.class_property import classproperty

# %% settings


@dataclass(frozen=True)
class WorkflowSettings:
    """
    Whose repositories the workflow writes to, and where it keeps its notes in them.
    """

    owner: str = "LucaKro"
    """
    The GitHub account whose repositories alone are written to.
    """

    notes_branch: str = "github-workflow/notes"
    """
    The branch the notes and progress live on, in every repository.
    """

    @classproperty
    def notes_reference(cls) -> str:
        """
        Where a fetch of the notes branch is kept, so neither a local branch nor
        ``FETCH_HEAD`` moves.
        """
        return "refs/github-workflow/notes"
