"""
Issues and pull requests a Markdown text names by bare number, ``#12``, which GitHub
links within the repository the text is on.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from domain_model.class_property import classproperty
from domain_model.repository import Repository

# %% the parts of a text


class MarkdownPart(StrEnum):
    """
    The parts of a Markdown text that matter to its bare issue numbers, each the name
    of its group in :attr:`IssueReferences.pattern`.
    """

    CODE_BLOCK = "code_block"
    """
    A fenced code block, whose text GitHub never links.
    """

    FENCE = "fence"
    """
    The run of backticks or tildes opening a code block, which closes it too.
    """

    CODE_SPAN = "code_span"
    """
    Inline code, whose text GitHub never links.
    """

    BACKTICKS = "backticks"
    """
    The run of backticks opening inline code, which closes it too.
    """

    COMMENT = "comment"
    """
    An HTML comment, which GitHub never shows.
    """

    NUMBER = "number"
    """
    An issue's or pull request's bare number, ``#`` and its digits.
    """


# %% qualifying them


@dataclass(frozen=True)
class IssueReferences:
    """
    The bare issue numbers of a Markdown text, outside code and comments, where GitHub
    links them.
    """

    text: str
    """
    The text.
    """

    @classproperty
    def pattern(cls) -> re.Pattern[str]:
        """
        A code block, inline code, an HTML comment, or a bare number not part of a
        word, a path or another reference.
        """
        return re.compile(
            rf"(?P<{MarkdownPart.CODE_BLOCK}>^(?P<{MarkdownPart.FENCE}>`{{3,}}|~{{3,}})"
            rf".*?^(?P={MarkdownPart.FENCE})[ \t]*$)"
            rf"|(?P<{MarkdownPart.CODE_SPAN}>(?P<{MarkdownPart.BACKTICKS}>`+)"
            rf".*?(?P={MarkdownPart.BACKTICKS}))"
            rf"|(?P<{MarkdownPart.COMMENT}><!--.*?-->)"
            rf"|(?<![\w/#&.-])(?P<{MarkdownPart.NUMBER}>#\d+)\b",
            re.MULTILINE | re.DOTALL,
        )

    def qualify(self, repository: Repository) -> str:
        """
        :param repository: The repository the text was written on.
        :return: The text with each bare number naming that repository too, as
            ``owner/name#12``, so it links there wherever the text is posted.
        """
        return self.pattern.sub(
            lambda found: (
                found.group()
                if found.group(MarkdownPart.NUMBER) is None
                else f"{repository.full_name}{found.group(MarkdownPart.NUMBER)}"
            ),
            self.text,
        )
