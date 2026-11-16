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

    @classmethod
    def appears_in(cls, text: str, namespace: str = Distribution.WORKFLOW) -> bool:
        """
        :param text: Markdown.
        :return: Whether it holds a comment in the form the workflow marks its own
            records with, whatever it marks.
        """
        return f"{CommentDelimiter.OPEN}{namespace}:" in text

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


# %% a part between two markers


@dataclass(frozen=True)
class MarkedPart:
    """
    A part of a Markdown text that only the workflow writes, between a comment starting
    it and one ending it, read back and replaced while the rest of the text is left as
    it is.
    """

    subject: str
    """
    What the part holds, such as ``why``.
    """

    @property
    def start(self) -> str:
        """:return: The comment the part starts after."""
        return WorkflowMarker(f"{self.subject}:start").line()

    @property
    def end(self) -> str:
        """:return: The comment the part ends before."""
        return WorkflowMarker(f"{self.subject}:end").line()

    def wrap(self, content: str) -> str:
        """
        :param content: What the part holds.
        :return: The part, its comments included.
        """
        return f"{self.start}\n{content.strip()}\n{self.end}"

    def read(self, text: str) -> str | None:
        """
        :param text: Markdown that may hold the part.
        :return: What its first such part holds, ``None`` when it holds none.
        """
        start = text.find(self.start)
        end = text.find(self.end, start)
        if start == -1 or end == -1:
            return None
        return text[start + len(self.start) : end].strip()

    def remove(self, text: str) -> str:
        """
        :param text: Markdown that may hold the part.
        :return: The text without its first such part, comments included.
        """
        start = text.find(self.start)
        end = text.find(self.end, start)
        if start == -1 or end == -1:
            return text
        around = (text[:start].rstrip(), text[end + len(self.end) :].strip())
        return "\n\n".join(piece for piece in around if piece)
