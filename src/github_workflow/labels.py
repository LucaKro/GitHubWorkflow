"""
The base every enumeration of the workflow's labels extends, and the labels it puts on
issues and pull requests outside the findings, whose labels are in
:mod:`github_workflow.findings`.
"""

from __future__ import annotations

from enum import ReprEnum

from domain_model.github.labels import GitHubLabel

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


# %% issues


class IssueLabel(DescribedLabel):
    """
    The labels the workflow puts on an issue about the pull requests working on it.
    """

    PULL_REQUEST_OPENED = (
        "pull request opened",
        "An open pull request of this repository closes it once merged",
        "5319e7",
    )
    """
    A draft whose description closes the issue is open.
    """


# %% pull requests


class PullRequestLabel(DescribedLabel):
    """
    The labels the person puts on a pull request to say how sessions treat it.
    """

    SHELVED = (
        "pull request: shelved",
        "Set aside by the person; sessions leave it alone unless it is named",
        "d4c5f9",
    )
    """
    Set aside by the person: left out of the pull requests a session works on.
    """


class UpstreamLabel(DescribedLabel):
    """
    The labels a fork's pull request carries about its upstream.
    """

    OPENED_UPSTREAM = (
        "opened upstream",
        "This pull request is open on the upstream repository",
        "1d76db",
    )
    """
    Opened on the repository the fork was forked from, by ``upstream``.
    """
