"""
The markers git writes into a file around each conflict a merge leaves.
"""

from __future__ import annotations

from enum import StrEnum

# %% conflict markers


class ConflictMarker(StrEnum):
    """
    The lines git writes into a file around each conflict a merge leaves, compared as
    the start of a line.
    """

    OURS = "<<<<<<< "
    """
    Opens a conflict, with the branch's own side.
    """

    THEIRS = ">>>>>>> "
    """
    Closes a conflict, after the merged branch's side.
    """

    @classmethod
    def left_in(cls, text: str) -> bool:
        """
        :param text: A file's text.
        :return: Whether a conflict is still marked in it.
        """
        return any(line.startswith(tuple(cls)) for line in text.splitlines())
