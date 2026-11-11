"""
A branch, and the commit it was at when it was read.
"""

from __future__ import annotations

from dataclasses import dataclass

from domain_model.git.revisions import CommitHash

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

    commit: CommitHash
    """
    The commit it was at.
    """

    def __str__(self) -> str:
        """:return: The branch and its commit, abbreviated."""
        return f"{self.branch} at {self.commit.abbreviated}"
