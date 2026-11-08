"""
An issue or pull request named by its number, as GitHub's Markdown links it.
"""

from __future__ import annotations

from dataclasses import dataclass

# %% the link


@dataclass(frozen=True)
class NumberLink:
    """
    A pull request or issue named by its number, as a Markdown link to its page.
    """

    number: int
    """
    Its number.
    """

    url: str
    """
    Its page on GitHub.
    """

    def markdown(self) -> str:
        """:return: The link, ``[#<number>](<url>)``."""
        return f"[#{self.number}]({self.url})"
