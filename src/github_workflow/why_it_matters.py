"""
Why a finding or a pull request matters, in a few sentences, kept where the workflow can
copy it word for word.
"""

from __future__ import annotations

from dataclasses import dataclass

from domain_model.class_property import classproperty

from github_workflow.exceptions import EmptyWhyError, WhyTooLongError
from github_workflow.markers import MarkedPart

# %% the why


@dataclass(frozen=True)
class WhyItMatters:
    """
    Why a finding or a pull request matters: who runs into the problem and what it costs
    them, kept in a finding's issue under a heading of its own, so that a pull request
    working on the finding can copy it word for word.
    """

    text: str
    """
    The why, as Markdown.
    """

    @classproperty
    def maximum_length(cls) -> int:
        """
        How many characters a why given to the workflow may hold.
        """
        return 600

    @classproperty
    def part(cls) -> MarkedPart:
        """
        The part of the issue's text that holds the why.
        """
        return MarkedPart("why")

    @classproperty
    def heading(cls) -> str:
        """
        The heading the why stands under in the issue.
        """
        return "## Why"

    @classmethod
    def from_text(cls, text: str) -> WhyItMatters:
        """
        :param text: A why given to the workflow.
        :return: The why.
        :raises EmptyWhyError: If it holds no text.
        :raises WhyTooLongError: If it is longer than :attr:`maximum_length`.
        """
        stripped = text.strip()
        if not stripped:
            raise EmptyWhyError()
        if len(stripped) > cls.maximum_length:
            raise WhyTooLongError(len(stripped), cls.maximum_length)
        return cls(stripped)

    @classmethod
    def read(cls, body: str) -> WhyItMatters | None:
        """
        :param body: An issue's text.
        :return: The why it holds, ``None`` when it holds none.
        """
        content = cls.part.read(body)
        if content is None:
            return None
        return cls(content.removeprefix(cls.heading).strip())

    def place(self, body: str) -> str:
        """
        :param body: An issue's text, which may hold a why already.
        :return: The text with this why after it, in place of the one it held.
        """
        rest = self.part.remove(body).rstrip()
        why = self.part.wrap(f"{self.heading}\n\n{self.text}")
        return f"{rest}\n\n{why}\n" if rest else f"{why}\n"
