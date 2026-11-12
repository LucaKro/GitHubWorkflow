"""
Reading one upstream pull request's checks and review state: over REST, the review
threads through REST or GraphQL, whichever the place it runs in reaches.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import StrEnum

from domain_model.environment import (
    ClaudeCodeVariable,
)
from domain_model.git.revisions import BranchName
from domain_model.github.clients import (
    GitHubApi,
    GitHubReader,
    GraphQLClient,
    RestClient,
)
from domain_model.github.commit_checks import CommitCheckReader
from domain_model.github.exceptions import (
    UpstreamPullRequestNotFound,
)
from domain_model.github.pull_request_models import UpstreamPullRequestSnapshot
from domain_model.github.rest_models import (
    RestPullRequest,
    RestReviewThread,
)
from domain_model.github.review_models import (
    BranchPullRequest,
    Review,
    ReviewThread,
    ReviewThreadPage,
    ThreadComment,
)
from domain_model.github.review_writers import (
    GraphQLReviewThreadWriter,
    RestReviewThreadWriter,
    ReviewThreadWriter,
)
from domain_model.github.routes import RepositoryRoute
from domain_model.github.vocabulary import (
    GraphQLDocument,
    PullRequestJSONKey,
    PullRequestState,
    QueryVariable,
)
from domain_model.repository import (
    Repository,
)

# %% reading


class PullRequestSource(ABC):
    """
    Reads one upstream pull request's checks and review state, by whichever API the
    place it runs in can reach.
    """

    upstream_repository: Repository
    """
    The repository the fork's pull requests are opened against.
    """

    fork_owner: str
    """
    The owner whose branches this reader will claim as its own.
    """

    @abstractmethod
    def resolve_pull_request_number(self, branch: BranchName) -> int:
        """
        Find the upstream pull request opened from *branch*.

        :param branch: The fork branch name.
        :return: The upstream pull request number.
        :raises UpstreamPullRequestNotFound: If the fork has no such pull request.
        """

    @abstractmethod
    def read_current_state(
        self, pull_request_number: int
    ) -> UpstreamPullRequestSnapshot:
        """
        Read the checks, reviews and review threads on one upstream pull request.

        :param pull_request_number: The upstream pull request's number.
        :return: The assembled snapshot.
        """

    def choose(self, branch: BranchName, pull_requests: list[BranchPullRequest]) -> int:
        """
        Pick the fork's own pull request out of those a branch search matched.

        Prefers an open pull request, falling back to the most recent closed one so a
        branch under post-merge discussion still resolves.

        :param branch: The fork branch searched for.
        :param pull_requests: Every match, newest first.
        :return: The chosen pull request's number.
        :raises UpstreamPullRequestNotFound: If none of them is the fork's.
        """
        candidates = [
            pull_request
            for pull_request in pull_requests
            if pull_request.head_owner.has_login(self.fork_owner)
        ]
        if not candidates:
            raise UpstreamPullRequestNotFound(
                branch, self.upstream_repository, self.fork_owner
            )
        open_candidates = [
            pull_request
            for pull_request in candidates
            if pull_request.state is PullRequestState.OPEN
        ]
        return (open_candidates or candidates)[0].number


# %% the review threads, by transport


class ReviewThreadSource(ABC):
    """
    Reads one pull request's review threads, by one transport.
    """

    @abstractmethod
    def threads(self, pull_request_number: int) -> list[ReviewThread]:
        """
        :param pull_request_number: The pull request's number.
        :return: Every review thread, in the order GitHub returned them.
        """


@dataclass(frozen=True)
class RestReviewThreadSource(ReviewThreadSource):
    """
    Reads review threads over the REST routes a Claude Code session's proxy adds, which
    GitHub itself does not have.
    """

    client: RestClient
    """
    How REST requests reach the proxy.
    """

    route: RepositoryRoute
    """
    The paths under the repository.
    """

    def threads(self, pull_request_number: int) -> list[ReviewThread]:
        comments = {
            comment.database_identifier: comment
            for comment in (
                ThreadComment.from_rest_json(entry)
                for page in self.client.get_pages(
                    self.route.review_comments(pull_request_number)
                )
                for entry in page
            )
        }
        return [
            RestReviewThread.from_json(entry).thread(comments)
            for entry in self.client.get(self.route.review_threads(pull_request_number))
        ]


@dataclass(frozen=True)
class GraphQLReviewThreadSource(ReviewThreadSource):
    """
    Reads review threads through GraphQL, which a runner or a developer's machine
    reaches and a Claude Code session does not.
    """

    client: GraphQLClient
    """
    How GraphQL queries reach GitHub.
    """

    repository: Repository
    """
    The repository the pull request is on.
    """

    def threads(self, pull_request_number: int) -> list[ReviewThread]:
        threads: list[ReviewThread] = []
        cursor: str | None = None
        while True:
            data = self.client.execute(
                GraphQLDocument.REVIEW_THREADS_PAGE.read(),
                {
                    QueryVariable.OWNER: self.repository.owner,
                    QueryVariable.NAME: self.repository.name,
                    QueryVariable.NUMBER: pull_request_number,
                    QueryVariable.THREAD_CURSOR: cursor,
                },
            )
            page = ReviewThreadPage.from_json(
                data[PullRequestJSONKey.REPOSITORY][PullRequestJSONKey.PULL_REQUEST][
                    PullRequestJSONKey.REVIEW_THREADS
                ]
            )
            threads.extend(page.threads)
            if not page.page_info.has_next_page:
                return threads
            cursor = page.page_info.end_cursor


# %% the whole pull request


@dataclass(frozen=True)
class GitHubPullRequestSource(PullRequestSource):
    """
    Reads one upstream pull request over REST, its review threads by the transport the
    place it runs in reaches, every read of it at once.
    """

    client: RestClient
    """
    How REST requests reach GitHub.
    """

    thread_source: ReviewThreadSource
    """
    Reads the review threads.
    """

    upstream_repository: Repository
    """
    The repository the fork's pull requests are opened against.
    """

    fork_owner: str
    """
    The owner whose branches this source claims as its own.
    """

    @property
    def route(self) -> RepositoryRoute:
        """:return: The paths under the upstream."""
        return RepositoryRoute(self.upstream_repository)

    def resolve_pull_request_number(self, branch: BranchName) -> int:
        pages = self.client.get_pages(
            self.route.pull_requests_for_head(self.fork_owner, branch)
        )
        return self.choose(
            branch,
            [
                RestPullRequest.from_json(entry).branch_pull_request
                for page in pages
                for entry in page
            ],
        )

    def read_current_state(
        self, pull_request_number: int
    ) -> UpstreamPullRequestSnapshot:
        route = self.route
        with ThreadPoolExecutor() as pool:
            read = pool.submit(self.client.get, route.pull_request(pull_request_number))
            reviews = pool.submit(
                self.client.get_pages, route.reviews(pull_request_number)
            )
            threads = pool.submit(self.thread_source.threads, pull_request_number)
            pull_request = RestPullRequest.from_json(read.result())
            checks = CommitCheckReader(self.client, route).checks(
                pull_request.head.commit
            )
            return UpstreamPullRequestSnapshot(
                number=pull_request.number,
                title=pull_request.title,
                url=pull_request.url,
                reviews=[
                    Review.from_json(entry)
                    for page in reviews.result()
                    for entry in page
                ],
                threads=threads.result(),
                checks=checks,
            )


class ReadSource(StrEnum):
    """
    The two APIs a pull request's review threads can be read and written through.
    """

    REST = "rest"
    """
    REST, the only one a Claude Code cloud session's proxy answers.
    """

    GRAPHQL = "graphql"
    """
    GraphQL, which a runner or a developer's own machine reaches.
    """

    @classmethod
    def detect(cls) -> ReadSource:
        """
        :return: The API the place this runs in can reach.
        """
        if ClaudeCodeVariable.REMOTE.read() == "true":
            return cls.REST
        return cls.GRAPHQL

    def reader(
        self,
        client: GitHubReader,
        upstream_repository: Repository,
        fork_owner: str,
    ) -> PullRequestSource:
        """
        :param client: The client every read goes through.
        :param upstream_repository: The repository to read.
        :param fork_owner: Whose branches to claim.
        :return: A source reading the pull request over REST, its threads through this
            API.
        """
        threads = (
            RestReviewThreadSource(client, RepositoryRoute(upstream_repository))
            if self is ReadSource.REST
            else GraphQLReviewThreadSource(client, upstream_repository)
        )
        return GitHubPullRequestSource(client, threads, upstream_repository, fork_owner)

    def writer(self, client: GitHubApi, repository: Repository) -> ReviewThreadWriter:
        """
        :param client: The client the writer goes through.
        :param repository: The repository whose review threads it writes.
        :return: The review thread writer for this API.
        """
        if self is ReadSource.REST:
            return RestReviewThreadWriter(client, repository)
        return GraphQLReviewThreadWriter(client, repository, client)
