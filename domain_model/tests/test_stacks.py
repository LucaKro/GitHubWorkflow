"""
Tests for native stacks: the models read from recorded Stacks REST API answers, and the
REST client's stack and retargeting calls against those answers replayed.
"""

from __future__ import annotations

import json
from http import HTTPStatus

from domain_model.github.clients import GitHubApi
from domain_model.github.replayed_api import RecordedAnswer, ReplayedApi
from domain_model.github.repository_client import GitHubRepository
from domain_model.github.routes import RepositoryRoute
from domain_model.github.stack_models import Stack
from domain_model.github.vocabulary import PullRequestState, RestJSONKey
from domain_model.repository import Repository

from .dataset.locations import DatasetLocation

REPOSITORY = Repository("an-owner", "a-repository")
"""
The repository every call in these tests is made against.
"""

# %% helpers


def recorded(location: DatasetLocation) -> object:
    """:param location: A recorded answer.
    :return: Its decoded body."""
    return json.loads(location.read_text())


def recorded_stack(location: DatasetLocation) -> Stack:
    """:param location: A recorded answer holding one stack, alone or in a list.
    :return: That stack."""
    body = recorded(location)
    return Stack.from_json(body[0] if isinstance(body, list) else body)


def client(api: ReplayedApi) -> GitHubRepository:
    """:param api: The replayed API.
    :return: A client calling it."""
    return GitHubRepository(REPOSITORY, GitHubApi("a-token", api.url))


def stacks_path(suffix: str = "") -> str:
    """:param suffix: What follows the stacks path.
    :return: The repository's stacks path."""
    return f"/repos/{REPOSITORY.full_name}/stacks{suffix}"


# %% models


def test_a_stack_reads_its_pull_requests_bottom_first():
    body = recorded(DatasetLocation.STACK_GROWN)

    stack = Stack.from_json(body)

    assert stack.numbers == [
        entry[RestJSONKey.NUMBER] for entry in body[RestJSONKey.PULL_REQUESTS]
    ]


def test_a_stack_names_the_branch_the_one_above_targets():
    stack = recorded_stack(DatasetLocation.STACK_GROWN)

    assert [entry.branch for entry in stack.pull_requests][:-1] == [
        entry[RestJSONKey.BASE][RestJSONKey.REFERENCE]
        for entry in recorded(DatasetLocation.STACK_GROWN)[RestJSONKey.PULL_REQUESTS]
    ][1:]


def test_a_merged_pull_request_in_a_stack_reads_as_merged():
    stack = recorded_stack(DatasetLocation.STACK_WITH_ITS_BOTTOM_MERGED)

    assert stack.pull_requests[0].state is PullRequestState.MERGED


# %% reading stacks


def test_the_stack_holding_a_pull_request_is_found_by_it():
    stack = recorded_stack(DatasetLocation.STACKS_HOLDING_A_PULL_REQUEST)
    middle = stack.numbers[1]
    path = stacks_path(f"?pull_request={middle}")
    answers = {
        ("GET", path): RecordedAnswer.from_file(
            HTTPStatus.OK, DatasetLocation.STACKS_HOLDING_A_PULL_REQUEST
        )
    }

    with ReplayedApi(answers) as api:
        found = client(api).stack_of(middle)

    assert found == stack


def test_a_pull_request_in_no_stack_has_none():
    path = stacks_path("?pull_request=1")
    answers = {
        ("GET", path): RecordedAnswer.from_file(
            HTTPStatus.OK, DatasetLocation.STACKS_HOLDING_NOTHING
        )
    }

    with ReplayedApi(answers) as api:
        assert client(api).stack_of(1) is None


def test_every_stack_is_listed():
    path = stacks_path(f"?per_page={RepositoryRoute.page_size}")
    answers = {
        ("GET", path): RecordedAnswer.from_file(
            HTTPStatus.OK, DatasetLocation.STACKS_LISTED
        )
    }

    with ReplayedApi(answers) as api:
        listed = client(api).stacks()

    assert listed == [
        Stack.from_json(entry) for entry in recorded(DatasetLocation.STACKS_LISTED)
    ]


def test_a_stack_is_read_by_its_number():
    stack = recorded_stack(DatasetLocation.STACK_READ)
    answers = {
        ("GET", stacks_path(f"/{stack.number}")): RecordedAnswer.from_file(
            HTTPStatus.OK, DatasetLocation.STACK_READ
        )
    }

    with ReplayedApi(answers) as api:
        assert client(api).stack(stack.number) == stack


# %% writing stacks


def test_creating_a_stack_sends_its_pull_requests_bottom_first():
    created = recorded_stack(DatasetLocation.STACK_CREATED)
    answers = {
        ("POST", stacks_path()): RecordedAnswer.from_file(
            HTTPStatus.CREATED, DatasetLocation.STACK_CREATED
        )
    }

    with ReplayedApi(answers) as api:
        stack = client(api).create_stack(created.numbers)

    assert api.sent[0].payload == {RestJSONKey.PULL_REQUESTS: created.numbers}
    assert stack == created


def test_growing_a_stack_sends_only_the_new_pull_requests():
    created = recorded_stack(DatasetLocation.STACK_CREATED)
    grown = recorded_stack(DatasetLocation.STACK_GROWN)
    added = grown.numbers[len(created.numbers) :]
    path = stacks_path(f"/{created.number}/add")
    answers = {
        ("POST", path): RecordedAnswer.from_file(
            HTTPStatus.OK, DatasetLocation.STACK_GROWN
        )
    }

    with ReplayedApi(answers) as api:
        stack = client(api).add_to_stack(created, added)

    assert api.sent[0].payload == {RestJSONKey.PULL_REQUESTS: added}
    assert stack == grown


def test_unstacking_every_pull_request_dissolves_the_stack():
    stack = recorded_stack(DatasetLocation.STACK_GROWN)
    path = stacks_path(f"/{stack.number}/unstack")
    answers = {("POST", path): RecordedAnswer(HTTPStatus.NO_CONTENT)}

    with ReplayedApi(answers) as api:
        assert client(api).unstack(stack) is None


def test_retargeting_sends_the_new_base():
    branch = "the-branch-below"
    path = f"/repos/{REPOSITORY.full_name}/pulls/7"
    answers = {("PATCH", path): RecordedAnswer(HTTPStatus.OK)}

    with ReplayedApi(answers) as api:
        client(api).set_base(7, branch)

    assert api.sent[0].payload == {RestJSONKey.BASE: branch}
