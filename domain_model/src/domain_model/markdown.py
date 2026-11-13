"""
The pieces of Markdown syntax this package writes and reads.
"""

from __future__ import annotations

from enum import StrEnum

# %% comments


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


# %% fenced code blocks


class CodeFence(StrEnum):
    """
    The lines opening and closing a fenced code block in Markdown.
    """

    MERMAID = "```mermaid"
    """
    Opens a block GitHub renders as a Mermaid diagram.
    """

    CLOSE = "```"
    """
    Closes the block.
    """
