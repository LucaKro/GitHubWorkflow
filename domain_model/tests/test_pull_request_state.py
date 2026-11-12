"""
Tests for :class:`domain_model.github.vocabulary.PullRequestState`: merged told apart
from closed, as REST reports a pull request.
"""

from __future__ import annotations

import json

import pytest

from domain_model.github.rest_models import RestPullRequest
from domain_model.github.vocabulary import PullRequestState

from .dataset.locations import DatasetLocation

# %% REST


@pytest.mark.parametrize(
    "payload, state",
    [
        (DatasetLocation.REST_PULL_REQUEST_MERGED, PullRequestState.MERGED),
        (DatasetLocation.REST_PULL_REQUEST_CLOSED_UNMERGED, PullRequestState.CLOSED),
    ],
    ids=["merged", "closed-unmerged"],
)
def test_rest_tells_merged_from_closed_by_the_merge_time(
    payload: DatasetLocation, state: PullRequestState
):
    """
    REST reports both as closed, so only the merge time tells them apart.
    """
    pull_request = RestPullRequest.from_json(json.loads(payload.read_text()))

    assert pull_request.branch_pull_request.state is state
