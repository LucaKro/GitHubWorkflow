"""
Tests for :class:`basstler_domain_model.github.vocabulary.PullRequestState`: one state,
whichever API reported it.
"""

from __future__ import annotations

import json

import pytest

from basstler_domain_model.github.rest_models import RestPullRequest
from basstler_domain_model.github.review_models import BranchPullRequest
from basstler_domain_model.github.vocabulary import PullRequestState

from .dataset.locations import DatasetLocation

# %% GraphQL


def test_graphql_spells_a_state_as_the_member_name():
    pull_request = BranchPullRequest.from_json(
        json.loads(DatasetLocation.GRAPHQL_BRANCH_PULL_REQUEST_MERGED.read_text())
    )

    assert pull_request.state is PullRequestState.MERGED


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
