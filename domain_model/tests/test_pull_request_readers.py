"""
Tests for :mod:`domain_model.github.readers`,
:mod:`domain_model.github.answer_recording` and
:class:`domain_model.github.commit_checks.CommitCheckReader`: reading a pull request's
checks and review state over REST, its threads through REST or GraphQL, and replaying
the answers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from domain_model.code_version import CodeVersion
from domain_model.git.revisions import BranchName
from domain_model.github.answer_recording import (
    AnswerRecording,
    GitHubRead,
    ReadTransport,
    RecordingClient,
    ReplayingClient,
)
from domain_model.github.clients import GitHubReader, GraphQLClient, RestClient
from domain_model.github.commit_checks import CommitCheckReader
from domain_model.github.exceptions import (
    RecordedReadMissingError,
    ReviewThreadWithoutCommentsError,
)
from domain_model.github.readers import (
    GitHubPullRequestSource,
    GraphQLReviewThreadSource,
    RestReviewThreadSource,
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


@dataclass
class AnswersByTransport(GitHubReader):
    """
    Answers REST paths with their recorded pages and GraphQL queries with the next
    recorded ``data``.
    """

    rest: RestPagesByPath
    """
    The REST answers.
    """

    graphql: GraphQLAnswersInOrder
    """
    The GraphQL answers.
    """

    def get(self, path: str) -> Any:
        return self.rest.get(path)

    def get_pages(self, path: str) -> list[Any]:
        return self.rest.get_pages(path)

    def execute(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        return self.graphql.execute(query, variables)


# %% review threads through GraphQL


def graphql_threads(*answers: DatasetLocation) -> GraphQLReviewThreadSource:
    """:param answers: The recorded ``data`` of each page, in order.
    :return: A GraphQL source of threads answered with them."""
    return GraphQLReviewThreadSource(
        GraphQLAnswersInOrder([recorded(answer) for answer in answers]), UPSTREAM
    )


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

    threads = graphql_threads(*pages).threads(10)

    assert [thread.identifier for thread in threads] == expected


def test_the_next_page_of_threads_is_read_after_the_last_one_s_cursor() -> None:
    first_page = recorded(DatasetLocation.GRAPHQL_THREADS_PAGE_ONE)
    client = GraphQLAnswersInOrder(
        [first_page, recorded(DatasetLocation.GRAPHQL_THREADS_PAGE_TWO)]
    )

    GraphQLReviewThreadSource(client, UPSTREAM).threads(10)

    cursor = first_page[PullRequestJSONKey.REPOSITORY][PullRequestJSONKey.PULL_REQUEST][
        PullRequestJSONKey.REVIEW_THREADS
    ][PullRequestJSONKey.PAGE_INFO][PullRequestJSONKey.END_CURSOR]
    assert [
        variables[QueryVariable.THREAD_CURSOR] for variables in client.variables_sent
    ] == [None, cursor]


# %% choosing a branch's pull request through REST


def rest_reader(pages: dict[str, list[Any]]) -> GitHubPullRequestSource:
    """:param pages: The pages of each path.
    :return: A source reading the pull request, its threads too, over REST answered
        with them."""
    client = RestPagesByPath(pages)
    return GitHubPullRequestSource(
        client, RestReviewThreadSource(client, ROUTE), UPSTREAM, FORK_OWNER
    )


def test_an_open_pull_request_on_a_later_page_is_chosen() -> None:
    open_pull_request = recorded(DatasetLocation.REST_PULLS_PAGE_TWO)[0]
    reader = rest_reader(
        {
            ROUTE.pull_requests_for_head(FORK_OWNER, BranchName("a-branch")): [
                recorded(DatasetLocation.REST_PULLS_PAGE_ONE),
                recorded(DatasetLocation.REST_PULLS_PAGE_TWO),
            ]
        }
    )

    assert (
        reader.resolve_pull_request_number(BranchName("a-branch"))
        == open_pull_request[RestJSONKey.NUMBER]
    )


# %% reading a pull request, its threads over REST


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


@pytest.fixture
def both_transports(rest_pages: dict[str, list[Any]]) -> AnswersByTransport:
    """:return: The pull request's REST answers, and its threads through GraphQL."""
    return AnswersByTransport(
        RestPagesByPath(rest_pages),
        GraphQLAnswersInOrder(
            [
                recorded(DatasetLocation.GRAPHQL_THREADS_PAGE_ONE),
                recorded(DatasetLocation.GRAPHQL_THREADS_PAGE_TWO),
            ]
        ),
    )


def graphql_source(client: GitHubReader) -> GitHubPullRequestSource:
    """:param client: Answers every read.
    :return: A source reading the pull request over REST, its threads through
        GraphQL."""
    return GitHubPullRequestSource(
        client, GraphQLReviewThreadSource(client, UPSTREAM), UPSTREAM, FORK_OWNER
    )


def test_a_read_replayed_from_its_recording_sees_the_same_pull_request(
    rest_pull_request: dict[str, Any], both_transports: AnswersByTransport
) -> None:
    number = rest_pull_request[RestJSONKey.NUMBER]
    recording = RecordingClient(both_transports)
    read = graphql_source(recording).read_current_state(number)

    again = graphql_source(ReplayingClient(recording.recording)).read_current_state(
        number
    )

    assert again == read


def test_a_recording_reads_back_as_written(
    rest_pull_request: dict[str, Any], both_transports: AnswersByTransport
) -> None:
    recording = RecordingClient(both_transports)
    graphql_source(recording).read_current_state(rest_pull_request[RestJSONKey.NUMBER])

    written = recording.recording.to_json()

    assert AnswerRecording.from_json(written) == recording.recording


def test_a_recording_names_the_code_that_made_it() -> None:
    assert AnswerRecording.started().recorder == CodeVersion.running()


def test_a_read_the_recording_lacks_is_refused_naming_both_versions() -> None:
    recorder = CodeVersion("0.1.0", None)
    client = ReplayingClient(AnswerRecording(recorder))

    with pytest.raises(RecordedReadMissingError) as raised:
        client.get(ROUTE.pull_request(10))

    assert (raised.value.read, raised.value.recorder, raised.value.replayer) == (
        GitHubRead(ReadTransport.REST, ROUTE.pull_request(10)).described,
        recorder,
        CodeVersion.running(),
    )


def test_a_read_is_answered_whatever_order_the_reads_come_in() -> None:
    recording = AnswerRecording(CodeVersion.running())
    first, second = ROUTE.pull_request(1), ROUTE.pull_request(2)
    recording.keep(GitHubRead(ReadTransport.REST, first), "first")
    recording.keep(GitHubRead(ReadTransport.REST, second), "second")
    client = ReplayingClient(recording)

    assert (client.get(second), client.get(first)) == ("second", "first")
