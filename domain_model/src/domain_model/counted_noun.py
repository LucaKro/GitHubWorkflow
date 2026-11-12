"""
A number of things, worded as a report names them.
"""

from __future__ import annotations

from dataclasses import dataclass

# %% a counted noun


@dataclass(frozen=True)
class CountedNoun:
    """
    A number of things, with the words naming one of them and several.
    """

    count: int
    """
    How many there are.
    """

    singular: str
    """
    The words naming one, such as ``branch``.
    """

    plural: str
    """
    The words naming several, such as ``branches``.
    """

    def __str__(self) -> str:
        """:return: The count, and the words agreeing with it."""
        return f"{self.count} {self.singular if self.count == 1 else self.plural}"
