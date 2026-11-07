"""
The errors raised by saving and loading the notes.
"""

from __future__ import annotations

from dataclasses import dataclass

from basstler_domain_model.exceptions import DataclassException

# %% saving notes


@dataclass
class NotesBlockMissingError(DataclassException, LookupError):
    """
    Raised when saving finds no notes block in ``CLAUDE.local.md``.
    """

    document: str
    """
    The file that was read.
    """

    def error_message(self) -> str:
        return f"{self.document} holds no github-workflow notes block"

    def suggest_correction(self) -> str:
        return "Start a session first, which writes the block, then edit inside it."
