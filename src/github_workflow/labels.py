"""
The labels the workflow puts on issues and pull requests, each enumerated with what it
means and its colour.
"""

from __future__ import annotations

from enum import ReprEnum

from basstler_domain_model.github.labels import GitHubLabel

# %% labels


class DescribedLabel(GitHubLabel, ReprEnum):
    """
    The base of an enumeration of labels: each member its own name, with what it means
    and its colour, which it is created with.
    """

    def __new__(cls, label: str, description: str, color: str) -> DescribedLabel:
        """
        :param label: The label's name, as GitHub stores it.
        :param description: What it means, which it is created with.
        :param color: Its colour, as six hexadecimal digits.
        :return: The member.
        """
        member = str.__new__(cls, label)
        member._value_ = label
        member.description = description
        member.color = color
        return member
