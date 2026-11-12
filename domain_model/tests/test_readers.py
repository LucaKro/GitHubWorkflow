"""
Tests for :class:`domain_model.github.readers.PullRequestSource`: choosing a branch's
pull request out of those a search matched.
"""

from __future__ import annotations

import pytest

from domain_model.git.revisions import BranchName
from domain_model.github.clients import GitHubApi
from domain_model.github.exceptions import UpstreamPullRequestNotFound
from domain_model.github.readers import PullRequestSource, RestReadSource
from domain_model.github.review_models import Author, BranchPullRequest
from domain_model.github.vocabulary import PullRequestState
from domain_model.repository import Repository

# %% choosing the fork's pull request


def source(fork_owner: str = "an-owner") -> PullRequestSource:
    """:param fork_owner: Whose branches to claim.
    :return: A source of the upstream's pull requests, claiming that owner's."""
    return RestReadSource().reader(
        GitHubApi("a-token"), Repository("upstream-owner", "a-repository"), fork_owner
    )


def build_branch_pull_request(
    number: int, state: PullRequestState, owner: str = "an-owner"
) -> BranchPullRequest:
    """
    :param number: The pull request's number.
    :param state: Where it stands.
    :param owner: The owner of its head branch.
    :return: The pull request as a branch search finds it.
    """
    return BranchPullRequest(number, state, Author(owner))


def test_the_fork_owner_is_matched_whatever_its_case() -> None:
    pull_request = build_branch_pull_request(7, PullRequestState.OPEN, "AnOwner")

    assert source("anowner").choose(BranchName("a-branch"), [pull_request]) == 7


def test_the_fork_s_open_pull_request_is_chosen_over_its_closed_ones() -> None:
    matches = [
        build_branch_pull_request(12, PullRequestState.CLOSED),
        build_branch_pull_request(10, PullRequestState.OPEN),
        build_branch_pull_request(8, PullRequestState.MERGED),
    ]

    assert source().choose(BranchName("a-branch"), matches) == 10


def test_without_an_open_one_the_fork_s_newest_pull_request_is_chosen() -> None:
    matches = [
        build_branch_pull_request(12, PullRequestState.MERGED),
        build_branch_pull_request(8, PullRequestState.CLOSED),
    ]

    assert source().choose(BranchName("a-branch"), matches) == 12


def test_another_owner_s_pull_request_is_never_chosen() -> None:
    matches = [build_branch_pull_request(10, PullRequestState.OPEN, "someone-else")]

    with pytest.raises(UpstreamPullRequestNotFound):
        source().choose(BranchName("a-branch"), matches)
