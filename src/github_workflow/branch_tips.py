"""
Branches, each with the commit it is at.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Self

from basstler_domain_model.class_property import classproperty

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


# %% several branches


@dataclass(frozen=True)
class BranchTips:
    """
    Branches, each with the commit it may be deleted at, as the notes branch lists them.
    """

    commits: Mapping[str, str] = field(default_factory=dict)
    """
    Each branch, and the commit it may be deleted at.
    """

    @classmethod
    def from_text(cls, text: str | None) -> Self:
        """
        :param text: The list as the notes branch keeps it, ``None`` when it has none.
        :return: The branches it names.
        """
        pairs = (line.split() for line in (text or "").splitlines() if line.strip())
        return cls({branch: commit for branch, commit in pairs})

    def to_text(self) -> str:
        """:return: The list as the notes branch keeps it."""
        return "".join(
            f"{branch} {commit}\n" for branch, commit in sorted(self.commits.items())
        )

    def extended(self, tip: BranchTip) -> Self:
        """
        :param tip: Another branch, and its commit.
        :return: These branches and that one.
        """
        return type(self)({**self.commits, tip.branch: tip.commit})
