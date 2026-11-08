"""
Tests for :class:`domain_model.github.readers.PullRequestSource`: choosing a branch's
pull request out of those a search matched.
"""

from __future__ import annotations

from domain_model.github.clients import GitHubApi
from domain_model.github.readers import RestPullRequestReader
from domain_model.github.review_models import Author, BranchPullRequest
from domain_model.github.vocabulary import PullRequestState
from domain_model.repository import Repository

# %% choosing the fork's pull request


def test_the_fork_owner_is_matched_whatever_its_case() -> None:
    reader = RestPullRequestReader(
        GitHubApi("a-token"), Repository("upstream-owner", "a-repository"), "anowner"
    )
    pull_request = BranchPullRequest(7, PullRequestState.OPEN, Author("AnOwner"))

    assert reader.choose("a-branch", [pull_request]) == pull_request.number
