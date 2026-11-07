"""
Tests for :class:`basstler_domain_model.github.discussions.DiscussionCategory`, which a
caller's own set of categories extends.
"""

from __future__ import annotations

from enum import ReprEnum

from basstler_domain_model.github.discussions import (
    DefaultDiscussionCategory,
    DiscussionCategory,
)

# %% an enumeration of categories


class EnumeratedCategory(DiscussionCategory, ReprEnum):
    """
    A caller's own categories, enumerated.
    """

    BRAINSTORMING = "Brainstorming notes"
    """
    A category the tests name.
    """


def test_a_caller_s_category_is_a_category():
    assert isinstance(EnumeratedCategory.BRAINSTORMING, DiscussionCategory)


def test_a_category_is_its_own_name():
    assert (
        f"{EnumeratedCategory.BRAINSTORMING}" == EnumeratedCategory.BRAINSTORMING.value
    )


def test_github_s_categories_are_categories():
    assert all(
        isinstance(category, DiscussionCategory)
        for category in DefaultDiscussionCategory
    )
