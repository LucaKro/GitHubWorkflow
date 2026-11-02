"""
One section of what a session starts with, computed from the owner's repository on
GitHub.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from basstler_domain_model.github.repository_client import GitHubRepository

from github_workflow.checkout import ProjectCheckout
from github_workflow.hooks import ReportLine
from github_workflow.remotes import OwnedRemote

# %% where a section looks


@dataclass(frozen=True)
class SectionContext:
    """
    The checkout a session starts in, and the owner's repository it works on.
    """

    checkout: ProjectCheckout
    """
    The checkout.
    """

    remote: OwnedRemote
    """
    The owner's remote, naming the repository.
    """

    github: GitHubRepository
    """
    The repository on GitHub.
    """


# %% one section


class ReportSection(ABC):
    """
    One part of the session start that reads, and may set up, the repository on GitHub.
    """

    @abstractmethod
    def lines(self) -> list[ReportLine]:
        """
        :return: What the session should know, empty when there is nothing to say.
        """
