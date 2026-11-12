"""
Tests for :mod:`domain_model.github.number_links`, and for the same link built from a
repository.
"""

from __future__ import annotations

from domain_model.github.rest_models import SearchedPullRequest
from domain_model.repository import Repository

# %% the link


def test_a_pull_request_links_its_number_to_its_page() -> None:
    url = "https://github.com/owner/project/pull/7"

    assert SearchedPullRequest(7, url, None).markdown_link == f"[#7]({url})"


def test_a_repository_links_an_issue_s_number_to_its_page() -> None:
    repository = Repository("owner", "project")

    assert repository.issue_link(7) == f"[#7]({repository.issue_url(7)})"
