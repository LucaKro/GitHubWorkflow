"""
The comments the workflow leaves in Markdown it writes, hidden from a person reading it
and read back by the workflow.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from github_workflow.plugin import Distribution

# %% a marker


class CommentDelimiter(StrEnum):
    """
    The text opening and closing a comment in Markdown.
    """

    OPEN = "<!-- "
    """
    Opens the comment.
    """

    CLOSE = " -->"
    """
    Closes the comment.
    """


@dataclass(eq=False)
class WorkflowMarker:
    """
    One comment the workflow marks something with, recording a value or nothing.
    """

    subject: str
    """
    What it marks, such as ``proof``.
    """

    namespace: str = Distribution.WORKFLOW
    """
    What tells the workflow's comments apart from any other.
    """

    @property
    def prefix(self) -> str:
        """:return: The comment up to the value it records."""
        return f"{CommentDelimiter.OPEN}{self.namespace}:{self.subject} "

    def line(self, value: str | None = None) -> str:
        """
        :param value: What the comment records, ``None`` for nothing.
        :return: The comment.
        """
        if value is None:
            return f"{self.prefix.rstrip()}{CommentDelimiter.CLOSE}"
        return f"{self.prefix}{value}{CommentDelimiter.CLOSE}"

    def read(self, text: str) -> str | None:
        """
        :param text: Markdown that may hold the comment.
        :return: What its first such comment records, ``None`` when it holds none.
        """
        start = text.find(self.prefix)
        if start == -1:
            return None
        recorded = text[start + len(self.prefix) :]
        return recorded.partition(CommentDelimiter.CLOSE)[0]
