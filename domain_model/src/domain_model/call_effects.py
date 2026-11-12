"""
What a program's call does beyond reading, found by reading its command line.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

# %% an effect


@dataclass(frozen=True)
class CallEffect(ABC):
    """
    What one call does beyond reading, and what it was seen doing it with.
    """

    @property
    @abstractmethod
    def description(self) -> str:
        """
        :return: What the call does, as a sentence naming the call.
        """

    @property
    def write(self) -> str | None:
        """
        :return: The subcommand, command or tool the call writes with, ``None`` when
            something else than the command it runs makes it more than a read.
        """
        return None
