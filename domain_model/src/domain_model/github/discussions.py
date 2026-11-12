"""
What a discussion category is, and the categories GitHub gives a repository.
"""

from __future__ import annotations

from enum import ReprEnum

# %% categories


class DiscussionCategory(str):
    """
    A category of a repository's Discussions, as GitHub names it: the category is its
    own name.

    The base a caller's own set of categories extends, an enumeration of them included.
    """


class DefaultDiscussionCategory(DiscussionCategory, ReprEnum):
    """
    The categories GitHub gives a repository when Discussions are turned on, which the
    repository's maintainers may rename or remove.
    """

    ANNOUNCEMENTS = "Announcements"
    """
    Updates from the maintainers.
    """

    GENERAL = "General"
    """
    Anything else.
    """

    IDEAS = "Ideas"
    """
    Ideas for the project.
    """

    POLLS = "Polls"
    """
    Questions put to a vote.
    """

    QUESTIONS_AND_ANSWERS = "Q&A"
    """
    Questions, each with an answer that can be marked.
    """

    SHOW_AND_TELL = "Show and tell"
    """
    What people made with the project.
    """
