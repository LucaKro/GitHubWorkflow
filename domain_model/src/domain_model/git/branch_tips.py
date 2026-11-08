"""
A branch, and the commit it was at when it was read.
"""

from __future__ import annotations

from dataclasses import dataclass

from domain_model.class_property import classproperty

# %% one branch


@dataclass(frozen=True)
class BranchTip:
    """
    The commit a branch was at when it was read.
    """

    branch: str
    """
    The branch.
    """

    commit: str
    """
    The commit it was at.
    """

    @classproperty
    def abbreviation_length(cls) -> int:
        """
        How many of a commit's leading hexadecimal digits name it in a report.
        """
        return 7

    @classmethod
    def abbreviated(cls, commit: str) -> str:
        """
        :param commit: A commit.
        :return: It, as a report names it.
        """
        return commit[: cls.abbreviation_length]

    def __str__(self) -> str:
        """:return: The branch and its commit, abbreviated."""
        return f"{self.branch} at {self.abbreviated(self.commit)}"
