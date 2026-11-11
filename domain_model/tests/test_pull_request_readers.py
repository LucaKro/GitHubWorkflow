"""
Tests for :mod:`domain_model.github.readers` and
:class:`domain_model.github.commit_checks.CommitCheckReader`: finding a branch's pull
request and reading its checks and review state, through GraphQL or REST.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from domain_model.github.clients import (
    GraphQLClient,
    RecordedAnswers,
    RecordingGraphQLClient,
    ReplayingGraphQLClient,
    RestClient,
)
from domain_model.github.commit_checks import CommitCheckReader
from domain_model.github.exceptions import (
    RecordedAnswersExhaustedError,
    ReviewThreadWithoutCommentsError,
    UpstreamPullRequestNotFound,
)
from domain_model.github.readers import (
    RestPullRequestReader,
    UpstreamPullRequestReader,
)
from domain_model.github.rest_models import RestReviewThread
from domain_model.github.routes import RepositoryRoute
from domain_model.github.vocabulary import (
    CheckOutcome,
    PullRequestJSONKey,
    QueryVariable,
    RestJSONKey,
    ReviewState,
    RollupState,
)
from domain_model.repository import Repository

from .dataset.locations import DatasetLocation

UPSTREAM = Repository("upstream-owner", "a-repository")
"""
The repository every pull request in these tests is opened against.
"""

FORK_OWNER = "a-fork-owner"
"""
The owner whose branches the readers claim.
"""

ROUTE = RepositoryRoute(UPSTREAM)
"""
The upstream's REST paths.
"""

# %% answers kept in memory


def recorded(location: DatasetLocation) -> Any:
    """:param location: A recorded payload.
    :return: It, decoded."""
    return json.loads(location.read_text())


@dataclass
class GraphQLAnswersInOrder(GraphQLClient):
    """
    Answers each GraphQL query with the next recorded ``data``, keeping the variables it
    was sent.
    """

    answers: list[dict[str, Any]]
    """
    The ``data`` of each answer, in the order they are given.
    """

    variables_sent: list[dict[str, Any]] = field(default_factory=list)
    """
    The variables of every query, in order.
    """

    def execute(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        self.variables_sent.append(variables)
        return self.answers.pop(0)


@dataclass
class RestPagesByPath(RestClient):
    """
    Answers each REST path with the pages recorded for it.
    """

    pages: dict[str, list[Any]]
    """
    The pages of each path, query included; a path read whole has one.
    """

    def get(self, path: str) -> Any:
        [page] = self.pages[path]
        return page

    def get_pages(self, path: str) -> list[Any]:
        return self.pages[path]


# %% choosing a branch's pull request through GraphQL


def graphql_reader(*answers: DatasetLocation) -> UpstreamPullRequestReader:
    """:param answers: The recorded ``data`` of each query, in order.
    :return: A GraphQL reader answered with them."""
    return UpstreamPullRequestReader(
        GraphQLAnswersInOrder([recorded(answer) for answer in answers]),
        UPSTREAM,
        FORK_OWNER,
    )


def test_the_fork_s_open_pull_request_is_chosen_over_its_closed_ones() -> None:
    reader = graphql_reader(DatasetLocation.GRAPHQL_BRANCH_SEARCH)

    assert reader.resolve_pull_request_number("a-branch") == 10


def test_without_an_open_one_the_fork_s_newest_pull_request_is_chosen() -> None:
    search = recorded(DatasetLocation.GRAPHQL_BRANCH_SEARCH_CLOSED)
    newest = search[PullRequestJSONKey.REPOSITORY][PullRequestJSONKey.PULL_REQUESTS][
        PullRequestJSONKey.NODES
    ][0]
    reader = graphql_reader(DatasetLocation.GRAPHQL_BRANCH_SEARCH_CLOSED)

    assert (
        reader.resolve_pull_request_number("a-branch")
        == newest[PullRequestJSONKey.NUMBER]
    )


def test_another_owner_s_pull_request_is_never_chosen() -> None:
    reader = graphql_reader(DatasetLocation.GRAPHQL_BRANCH_SEARCH_FOREIGN)

    with pytest.raises(UpstreamPullRequestNotFound):
        reader.resolve_pull_request_number("a-branch")


# %% reading a pull request through GraphQL


def test_every_page_of_review_threads_is_gathered() -> None:
    pages = [
        DatasetLocation.GRAPHQL_THREADS_PAGE_ONE,
        DatasetLocation.GRAPHQL_THREADS_PAGE_TWO,
    ]
    expected = [
        node[PullRequestJSONKey.IDENTIFIER]
        for page in pages
        for node in recorded(page)[PullRequestJSONKey.REPOSITORY][
            PullRequestJSONKey.PULL_REQUEST
        ][PullRequestJSONKey.REVIEW_THREADS][PullRequestJSONKey.NODES]
    ]

    snapshot = graphql_reader(*pages).read_current_state(10)

    assert [thread.identifier for thread in snapshot.threads] == expected


def test_the_next_page_of_threads_is_read_after_the_last_one_s_cursor() -> None:
    first_page = recorded(DatasetLocation.GRAPHQL_THREADS_PAGE_ONE)
    client = GraphQLAnswersInOrder(
        [first_page, recorded(DatasetLocation.GRAPHQL_THREADS_PAGE_TWO)]
    )

    UpstreamPullRequestReader(client, UPSTREAM, FORK_OWNER).read_current_state(10)

    cursor = first_page[PullRequestJSONKey.REPOSITORY][PullRequestJSONKey.PULL_REQUEST][
        PullRequestJSONKey.REVIEW_THREADS
    ][PullRequestJSONKey.PAGE_INFO][PullRequestJSONKey.END_CURSOR]
    assert [
        variables[QueryVariable.THREAD_CURSOR] for variables in client.variables_sent
    ] == [
        None,
        cursor,
    ]


# %% choosing a branch's pull request through REST


def rest_reader(pages: dict[str, list[Any]]) -> RestPullRequestReader:
    """:param pages: The pages of each path.
    :return: A REST reader answered with them."""
    return RestPullRequestReader(RestPagesByPath(pages), UPSTREAM, FORK_OWNER)


def test_an_open_pull_request_on_a_later_page_is_chosen() -> None:
    open_pull_request = recorded(DatasetLocation.REST_PULLS_PAGE_TWO)[0]
    reader = rest_reader(
        {
            ROUTE.pull_requests_for_head(FORK_OWNER, "a-branch"): [
                recorded(DatasetLocation.REST_PULLS_PAGE_ONE),
                recorded(DatasetLocation.REST_PULLS_PAGE_TWO),
            ]
        }
    )

    assert (
        reader.resolve_pull_request_number("a-branch")
        == open_pull_request[RestJSONKey.NUMBER]
    )


# %% reading a pull request through REST


@pytest.fixture
def rest_pull_request() -> dict[str, Any]:
    """:return: The pull request the REST reader reads."""
    return recorded(DatasetLocation.REST_PULL_REQUEST)


@pytest.fixture
def rest_pages(rest_pull_request: dict[str, Any]) -> dict[str, list[Any]]:
    """:return: Every path the REST reader reads the pull request through, answered."""
    number = rest_pull_request[RestJSONKey.NUMBER]
    sha = rest_pull_request[RestJSONKey.HEAD][RestJSONKey.SHA]
    return {
        ROUTE.pull_request(number): [rest_pull_request],
        ROUTE.reviews(number): [recorded(DatasetLocation.REST_REVIEWS)],
        ROUTE.review_comments(number): [recorded(DatasetLocation.REST_REVIEW_COMMENTS)],
        ROUTE.review_threads(number): [recorded(DatasetLocation.REST_REVIEW_THREADS)],
        ROUTE.check_runs(sha): [recorded(DatasetLocation.REST_CHECK_RUNS)],
        ROUTE.commit_status(sha): [recorded(DatasetLocation.REST_COMMIT_STATUS)],
    }


def test_a_rest_read_carries_the_submitted_reviews(
    rest_pull_request: dict[str, Any], rest_pages: dict[str, list[Any]]
) -> None:
    [review] = recorded(DatasetLocation.REST_REVIEWS)

    snapshot = rest_reader(rest_pages).read_current_state(
        rest_pull_request[RestJSONKey.NUMBER]
    )

    assert [
        (submitted.author.login, submitted.state) for submitted in snapshot.reviews
    ] == [
        (
            review[RestJSONKey.USER][RestJSONKey.LOGIN],
            ReviewState[review[RestJSONKey.STATE]],
        )
    ]


def test_a_rest_thread_is_filled_in_with_its_comments(
    rest_pull_request: dict[str, Any], rest_pages: dict[str, list[Any]]
) -> None:
    [thread] = recorded(DatasetLocation.REST_REVIEW_THREADS)

    snapshot = rest_reader(rest_pages).read_current_state(
        rest_pull_request[RestJSONKey.NUMBER]
    )

    assert [
        comment.database_identifier for comment in snapshot.threads[0].comments
    ] == thread[RestJSONKey.COMMENT_IDENTIFIERS]


def test_a_rest_thread_without_comments_is_refused() -> None:
    with pytest.raises(ReviewThreadWithoutCommentsError):
        RestReviewThread.from_json(
            recorded(DatasetLocation.REST_REVIEW_THREAD_WITHOUT_COMMENTS)
        )


def test_a_rest_read_carries_the_head_commit_s_checks(
    rest_pull_request: dict[str, Any], rest_pages: dict[str, list[Any]]
) -> None:
    snapshot = rest_reader(rest_pages).read_current_state(
        rest_pull_request[RestJSONKey.NUMBER]
    )

    assert snapshot.checks is not None
    assert snapshot.checks.state is RollupState.FAILURE


# %% reading a commit's checks


def check_reader(runs: DatasetLocation, statuses: DatasetLocation) -> CommitCheckReader:
    """
    :param runs: The recorded check runs on commit ``a1b2c3``.
    :param statuses: The recorded commit statuses on it.
    :return: A reader of its checks.
    """
    return CommitCheckReader(
        RestPagesByPath(
            {
                ROUTE.check_runs("a1b2c3"): [recorded(runs)],
                ROUTE.commit_status("a1b2c3"): [recorded(statuses)],
            }
        ),
        ROUTE,
    )


def test_check_runs_and_commit_statuses_are_combined_in_that_order() -> None:
    runs = recorded(DatasetLocation.REST_CHECK_RUNS)[RestJSONKey.CHECK_RUNS]
    statuses = recorded(DatasetLocation.REST_COMMIT_STATUS)[RestJSONKey.STATUSES]
    reader = check_reader(
        DatasetLocation.REST_CHECK_RUNS, DatasetLocation.REST_COMMIT_STATUS
    )

    checks = reader.checks("a1b2c3")

    assert checks is not None
    assert [result.name for result in checks.results] == [
        run[RestJSONKey.NAME] for run in runs
    ] + [status[RestJSONKey.CONTEXT] for status in statuses]


def test_an_unfinished_check_run_reads_as_pending() -> None:
    reader = check_reader(
        DatasetLocation.REST_CHECK_RUNS, DatasetLocation.REST_COMMIT_STATUS_NONE
    )

    checks = reader.checks("a1b2c3")

    assert checks is not None
    assert [result.outcome for result in checks.results] == [
        CheckOutcome.SUCCESS,
        CheckOutcome.PENDING,
    ]


def test_a_commit_nothing_reported_on_has_no_checks() -> None:
    reader = check_reader(
        DatasetLocation.REST_CHECK_RUNS_NONE, DatasetLocation.REST_COMMIT_STATUS_NONE
    )

    assert reader.checks("a1b2c3") is None


# %% recorded and replayed answers


def test_recorded_answers_read_back_as_written() -> None:
    answers = RecordedAnswers([recorded(DatasetLocation.GRAPHQL_BRANCH_SEARCH)])

    assert RecordedAnswers.from_json(answers.to_json()) == answers


def test_a_read_replayed_from_its_recorded_answers_sees_the_same_pull_request():
    recording = RecordingGraphQLClient(
        GraphQLAnswersInOrder(
            [
                recorded(DatasetLocation.GRAPHQL_BRANCH_SEARCH),
                recorded(DatasetLocation.GRAPHQL_THREADS_PAGE_ONE),
                recorded(DatasetLocation.GRAPHQL_THREADS_PAGE_TWO),
            ]
        )
    )
    original = UpstreamPullRequestReader(recording, UPSTREAM, FORK_OWNER)
    read = original.read_current_state(original.resolve_pull_request_number("a-branch"))

    replayed = UpstreamPullRequestReader(
        ReplayingGraphQLClient(recording.answers), UPSTREAM, FORK_OWNER
    )
    again = replayed.read_current_state(
        replayed.resolve_pull_request_number("a-branch")
    )

    assert again == read


def test_a_query_past_the_recorded_answers_is_refused():
    client = ReplayingGraphQLClient(
        RecordedAnswers([recorded(DatasetLocation.GRAPHQL_BRANCH_SEARCH)])
    )
    client.execute("query", {})

    with pytest.raises(RecordedAnswersExhaustedError):
        client.execute("query", {})
