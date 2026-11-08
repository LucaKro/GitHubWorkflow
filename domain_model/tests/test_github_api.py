"""
Tests for :class:`domain_model.github.clients.GitHubApi`: REST, GraphQL and job logs
over HTTP, against answers replayed by a local server.
"""

from __future__ import annotations

import json
import socket
from collections.abc import Iterator
from http import HTTPStatus

import pytest

from domain_model.github.clients import GitHubApi
from domain_model.github.exceptions import (
    GitHubRequestFailed,
    GraphQLDataMissingError,
    GraphQLErrorsReturned,
)
from domain_model.github.replayed_api import RecordedAnswer, ReplayedApi
from domain_model.github.vocabulary import PullRequestJSONKey
from domain_model.repository import Repository

from .dataset.locations import DatasetLocation

TOKEN = "a-token"
"""
The token every client in these tests calls with.
"""

REPOSITORY = Repository("an-owner", "a-repository")
"""
The repository the job logs are read from.
"""

# %% REST


def test_a_response_is_read_from_its_path():
    path = f"/{REPOSITORY.api_path}/pulls/1"
    answers = {
        ("GET", path): RecordedAnswer.from_file(HTTPStatus.OK, DatasetLocation.PAGE_ONE)
    }

    with ReplayedApi(answers) as api:
        read = GitHubApi(TOKEN, api.url).get(path)

    assert read == json.loads(DatasetLocation.PAGE_ONE.read_text())
    assert api.sent[0].authorization == f"Bearer {TOKEN}"


def test_every_page_is_collected_by_following_the_next_link():
    first, second = (
        f"/{REPOSITORY.api_path}/pulls",
        f"/{REPOSITORY.api_path}/pulls?page=2",
    )
    with ReplayedApi() as api:
        api.answers[("GET", first)] = RecordedAnswer(
            HTTPStatus.OK,
            DatasetLocation.PAGE_ONE.read_text(),
            {"Link": f'<{api.url}{second}>; rel="next"'},
        )
        api.answers[("GET", second)] = RecordedAnswer.from_file(
            HTTPStatus.OK, DatasetLocation.PAGE_TWO
        )

        pages = GitHubApi(TOKEN, api.url).get_pages(first)

    assert pages == [
        json.loads(DatasetLocation.PAGE_ONE.read_text()),
        json.loads(DatasetLocation.PAGE_TWO.read_text()),
    ]


def test_a_refused_call_is_raised_with_its_status():
    with ReplayedApi() as api:
        with pytest.raises(GitHubRequestFailed) as raised:
            GitHubApi(TOKEN, api.url).get("/repos/missing")

    assert raised.value.status == HTTPStatus.NOT_FOUND


def test_an_attempt_reports_a_refusal_instead_of_raising_it():
    path = "/user"
    answers = {
        ("GET", path): RecordedAnswer.from_file(
            HTTPStatus.FORBIDDEN, DatasetLocation.REFUSAL
        )
    }

    with ReplayedApi(answers) as api:
        answer = GitHubApi(TOKEN, api.url).attempt("GET", path)

    assert answer.status == HTTPStatus.FORBIDDEN
    assert answer.body == json.loads(DatasetLocation.REFUSAL.read_text())


# %% redirects


def test_a_write_redirected_temporarily_is_repeated_at_the_new_address() -> None:
    old, new = f"/{REPOSITORY.api_path}", "/repos/an-owner/a-new-name"
    payload = {"has_issues": True}
    with ReplayedApi() as api:
        api.answers[("PATCH", old)] = RecordedAnswer(
            HTTPStatus.TEMPORARY_REDIRECT, headers={"Location": f"{api.url}{new}"}
        )
        api.answers[("PATCH", new)] = RecordedAnswer(HTTPStatus.OK, "{}")

        GitHubApi(TOKEN, api.url).request("PATCH", old, payload)

    assert [(sent.method, sent.path, sent.payload) for sent in api.sent] == [
        ("PATCH", old, payload),
        ("PATCH", new, payload),
    ]


def test_a_write_moved_permanently_is_not_replayed_as_a_read() -> None:
    old, new = f"/{REPOSITORY.api_path}", "/repos/an-owner/a-new-name"
    with ReplayedApi() as api:
        api.answers[("PATCH", old)] = RecordedAnswer(
            HTTPStatus.MOVED_PERMANENTLY, headers={"Location": f"{api.url}{new}"}
        )
        api.answers[("GET", new)] = RecordedAnswer(HTTPStatus.OK, "{}")

        with pytest.raises(GitHubRequestFailed) as raised:
            GitHubApi(TOKEN, api.url).request("PATCH", old, {"has_issues": True})

    assert raised.value.status == HTTPStatus.MOVED_PERMANENTLY


def test_a_write_answered_with_see_other_reads_the_address_named() -> None:
    old, new = f"/{REPOSITORY.api_path}", "/repos/an-owner/a-new-name"
    with ReplayedApi() as api:
        api.answers[("POST", old)] = RecordedAnswer(
            HTTPStatus.SEE_OTHER, headers={"Location": f"{api.url}{new}"}
        )
        api.answers[("GET", new)] = RecordedAnswer.from_file(
            HTTPStatus.OK, DatasetLocation.PAGE_ONE
        )

        read = GitHubApi(TOKEN, api.url).request("POST", old, {"has_issues": True})

    assert read == json.loads(DatasetLocation.PAGE_ONE.read_text())


def test_a_relative_redirect_is_followed_on_the_api_s_host_with_the_token() -> None:
    old, new = f"/{REPOSITORY.api_path}", "/repos/an-owner/a-new-name"
    answers = {
        ("GET", old): RecordedAnswer(
            HTTPStatus.MOVED_PERMANENTLY, headers={"Location": new}
        ),
        ("GET", new): RecordedAnswer.from_file(HTTPStatus.OK, DatasetLocation.PAGE_ONE),
    }

    with ReplayedApi(answers) as api:
        GitHubApi(TOKEN, api.url).get(old)

    assert (api.sent[1].path, api.sent[1].authorization) == (new, f"Bearer {TOKEN}")


# %% calls that get no answer


@pytest.fixture
def silent_address() -> Iterator[str]:
    """:return: An address that accepts connections and never answers them."""
    with socket.create_server(("127.0.0.1", 0)) as listening:
        host, port = listening.getsockname()
        yield f"http://{host}:{port}"


def test_a_call_that_gets_no_answer_in_time_is_raised_without_a_status(
    silent_address: str,
) -> None:
    with pytest.raises(GitHubRequestFailed) as raised:
        GitHubApi(TOKEN, silent_address, timeout_seconds=0.2).get("/user")

    assert raised.value.status is None


def test_a_call_that_cannot_connect_is_raised_without_a_status() -> None:
    with socket.create_server(("127.0.0.1", 0)) as closed:
        host, port = closed.getsockname()

    with pytest.raises(GitHubRequestFailed) as raised:
        GitHubApi(TOKEN, f"http://{host}:{port}").get("/user")

    assert raised.value.status is None


# %% GraphQL


def test_a_query_and_its_variables_are_sent_and_its_data_unwrapped():
    answers = {
        ("POST", "/graphql"): RecordedAnswer.from_file(
            HTTPStatus.OK, DatasetLocation.GRAPHQL_DATA
        )
    }
    query, variables = "query { viewer { login } }", {"number": 1}

    with ReplayedApi(answers) as api:
        data = GitHubApi(TOKEN, api.url).execute(query, variables)

    assert api.sent[0].payload == {
        PullRequestJSONKey.QUERY: query,
        PullRequestJSONKey.VARIABLES: variables,
    }
    assert (
        data
        == json.loads(DatasetLocation.GRAPHQL_DATA.read_text())[PullRequestJSONKey.DATA]
    )


def test_graphql_errors_are_raised_rather_than_returned():
    answers = {
        ("POST", "/graphql"): RecordedAnswer.from_file(
            HTTPStatus.OK, DatasetLocation.GRAPHQL_ERRORS
        )
    }

    with ReplayedApi(answers) as api:
        with pytest.raises(GraphQLErrorsReturned) as raised:
            GitHubApi(TOKEN, api.url).execute("query {}", {})

    recorded = json.loads(DatasetLocation.GRAPHQL_ERRORS.read_text())[
        PullRequestJSONKey.ERRORS
    ]
    assert raised.value.messages == [
        error[PullRequestJSONKey.MESSAGE] for error in recorded
    ]


def test_a_graphql_answer_with_neither_data_nor_errors_is_refused():
    answers = {
        ("POST", "/graphql"): RecordedAnswer.from_file(
            HTTPStatus.OK, DatasetLocation.GRAPHQL_NO_DATA
        )
    }

    with ReplayedApi(answers) as api:
        with pytest.raises(GraphQLDataMissingError):
            GitHubApi(TOKEN, api.url).execute("query {}", {})


# %% job logs


def test_a_job_log_is_followed_to_storage_without_the_token():
    """
    GitHub answers a job log with a redirect to blob storage, which must not be sent the
    token.
    """
    log_path = f"/{REPOSITORY.job_log_path(7)}"
    with ReplayedApi() as storage, ReplayedApi() as github:
        storage.answers[("GET", "/log")] = RecordedAnswer.from_file(
            HTTPStatus.OK, DatasetLocation.JOB_LOG
        )
        github.answers[("GET", log_path)] = RecordedAnswer(
            HTTPStatus.FOUND, headers={"Location": f"{storage.url}/log"}
        )

        log = GitHubApi(TOKEN, github.url).read_job_log(REPOSITORY, 7)

    assert log == DatasetLocation.JOB_LOG.read_text()
    assert storage.sent[0].authorization is None
