"""
Issues and pull requests named by their number, as GitHub's Markdown links them.
"""

from __future__ import annotations

from domain_model.class_property import classproperty

# %% the link


class HasNumberLink:
    """
    A pull request or issue with a number and a page, linked by its number.
    """

    number: int
    """
    Its number.
    """

    url: str
    """
    Its page on GitHub.
    """

    @classproperty
    def link_format(cls) -> str:
        """
        How GitHub's Markdown links an issue or pull request by its number, to fill with
        ``number`` and ``url``.
        """
        return "[#{number}]({url})"

    @property
    def markdown_link(self) -> str:
        """:return: The link, ``[#<number>](<url>)``."""
        return self.link_format.format(number=self.number, url=self.url)
