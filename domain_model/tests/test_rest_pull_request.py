"""
Tests for :class:`domain_model.github.rest_models.RestPullRequest`: a pull request
parsed as it arrives, and refused when it lacks what it cannot be read without.
"""

from __future__ import annotations

import json
from http import HTTPStatus
from typing import Any

import pytest

from domain_model.github.clients import GitHubApi
from domain_model.github.exceptions import MissingPullRequestFieldError
from domain_model.github.replayed_api import RecordedAnswer, ReplayedApi
from domain_model.github.repository_client import GitHubRepository
from domain_model.github.rest_models import PullRequestHead, RestPullRequest
from domain_model.github.review_models import Author
from domain_model.github.routes import RepositoryRoute
from domain_model.github.vocabulary import (
    MergeableState,
    PullRequestState,
    QueryParameter,
    RestJSONKey,
)
from domain_model.repository import Repository

from .dataset.locations import DatasetLocation

# %% fixtures


@pytest.fixture
def record() -> dict[str, Any]:
    """:return: An open draft pull request as REST answers it."""
    return json.loads(DatasetLocation.PULL_REQUEST_OPEN.read_text())


def read_payload(location: DatasetLocation) -> dict[str, Any]:
    """:param location: A recorded pull request.
    :return: It, decoded."""
    return json.loads(location.read_text())


# %% parsing


def test_a_pull_request_is_parsed_into_its_fields(record: dict[str, Any]) -> None:
    head = record[RestJSONKey.HEAD]

    assert RestPullRequest.from_json(record) == RestPullRequest(
        number=record[RestJSONKey.NUMBER],
        title=record[RestJSONKey.TITLE],
        body=record[RestJSONKey.BODY],
        url=record[RestJSONKey.HTML_URL],
        state=PullRequestState(record[RestJSONKey.STATE]),
        merged=False,
        draft=record[RestJSONKey.DRAFT],
        head=PullRequestHead(
            branch=head[RestJSONKey.REFERENCE],
            repository=head[RestJSONKey.REPOSITORY][RestJSONKey.FULL_NAME],
            commit=head[RestJSONKey.SHA],
            owner=Author(head[RestJSONKey.USER][RestJSONKey.LOGIN]),
        ),
        base=record[RestJSONKey.BASE][RestJSONKey.REFERENCE],
        labels=tuple(label[RestJSONKey.NAME] for label in record[RestJSONKey.LABELS]),
        mergeable_state=MergeableState(record[RestJSONKey.MERGEABLE_STATE]),
    )


def test_a_listed_pull_request_has_no_mergeable_state(record: dict[str, Any]) -> None:
    del record[RestJSONKey.MERGEABLE_STATE]

    assert RestPullRequest.from_json(record).mergeable_state is None


def test_a_pull_request_missing_a_required_field_is_refused_naming_it() -> None:
    with pytest.raises(MissingPullRequestFieldError) as raised:
        RestPullRequest.from_json(
            read_payload(DatasetLocation.PULL_REQUEST_WITHOUT_DRAFT)
        )

    assert raised.value.field_name is RestJSONKey.DRAFT


def test_a_head_whose_repository_was_deleted_has_none() -> None:
    pull_request = RestPullRequest.from_json(
        read_payload(DatasetLocation.PULL_REQUEST_HEAD_REPOSITORY_DELETED)
    )

    assert pull_request.head.repository is None


def test_a_head_without_its_commit_is_refused() -> None:
    with pytest.raises(MissingPullRequestFieldError) as raised:
        RestPullRequest.from_json(
            read_payload(DatasetLocation.PULL_REQUEST_HEAD_WITHOUT_COMMIT)
        )

    assert raised.value.field_name is RestJSONKey.HEAD


# %% read through the repository client

REPOSITORY = Repository("an-owner", "a-repository")
"""
The repository the client reads.
"""

ROUTE = RepositoryRoute(REPOSITORY)
"""
Its REST paths.
"""


def test_a_pull_request_is_read_parsed(record: dict[str, Any]) -> None:
    number = record[RestJSONKey.NUMBER]
    answers = {
        ("GET", f"/{ROUTE.pull_request(number)}"): RecordedAnswer.from_file(
            HTTPStatus.OK, DatasetLocation.PULL_REQUEST_OPEN
        )
    }

    with ReplayedApi(answers) as api:
        read = GitHubRepository(REPOSITORY, GitHubApi("a-token", api.url)).pull_request(
            number
        )

    assert read == RestPullRequest.from_json(record)


def test_open_pull_requests_are_listed_parsed(record: dict[str, Any]) -> None:
    listing = ROUTE.listing(
        ROUTE.pull_requests, {QueryParameter.STATE: PullRequestState.OPEN}
    )
    answers = {
        ("GET", f"/{listing}"): RecordedAnswer(HTTPStatus.OK, json.dumps([record]))
    }

    with ReplayedApi(answers) as api:
        listed = GitHubRepository(
            REPOSITORY, GitHubApi("a-token", api.url)
        ).open_pull_requests()

    assert listed == [RestPullRequest.from_json(record)]
