"""
Reading one upstream pull request's checks and review state, through GraphQL or REST.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from basstler_domain_model.environment import (
    ClaudeCodeVariable,
)
from basstler_domain_model.repository import (
    Repository,
)
from basstler_domain_model.github.clients import GitHubApi, GraphQLClient, RestClient
from basstler_domain_model.github.commit_checks import CommitCheckReader
from basstler_domain_model.github.routes import RepositoryRoute
from basstler_domain_model.github.exceptions import (
    UpstreamPullRequestNotFound,
)
from basstler_domain_model.github.pull_request_models import (
    PullRequestForBranchResult,
    ReviewThreadsPageResult,
    UpstreamPullRequestSnapshot,
)
from basstler_domain_model.github.rest_models import (
    RestPullRequest,
    RestReviewThread,
)
from basstler_domain_model.github.review_writers import (
    GraphQLReviewThreadWriter,
    RestReviewThreadWriter,
    ReviewThreadWriter,
)
from basstler_domain_model.github.review_models import (
    BranchPullRequest,
    Review,
    ReviewThread,
    ThreadComment,
)
from basstler_domain_model.github.vocabulary import (
    GraphQLDocument,
    PullRequestState,
    QueryVariable,
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
    def resolve_pull_request_number(self, branch: str) -> int:
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

    def choose(self, branch: str, pull_requests: list[BranchPullRequest]) -> int:
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


@dataclass
class UpstreamPullRequestReader(PullRequestSource):
    """
    Reads one upstream pull request's checks and review state through GraphQL, which a
    runner reaches and a Claude Code session does not.
    """

    client: GraphQLClient
    """
    How GraphQL queries reach GitHub.
    """

    upstream_repository: Repository
    """
    The repository the fork's pull requests are opened against.
    """

    fork_owner: str
    """
    The owner whose branches this reader will claim as its own.
    """

    @property
    def _repository_variables(self) -> dict[str, Any]:
        """:return: The owner and name every query in this script takes."""
        return {
            QueryVariable.OWNER: self.upstream_repository.owner,
            QueryVariable.NAME: self.upstream_repository.name,
        }

    def resolve_pull_request_number(self, branch: str) -> int:
        """
        See :meth:`PullRequestSource.resolve_pull_request_number`.
        """
        data = self.client.execute(
            GraphQLDocument.PULL_REQUEST_FOR_BRANCH.read(),
            {**self._repository_variables, QueryVariable.HEAD_REF_NAME: branch},
        )
        return self.choose(
            branch, PullRequestForBranchResult.from_json(data).pull_requests
        )

    def read_current_state(
        self, pull_request_number: int
    ) -> UpstreamPullRequestSnapshot:
        """
        See :meth:`PullRequestSource.read_current_state`.
        """
        threads: list[ReviewThread] = []
        cursor: str | None = None
        while True:
            pull_request = ReviewThreadsPageResult.from_json(
                self.client.execute(
                    GraphQLDocument.REVIEW_THREADS_PAGE.read(),
                    {
                        **self._repository_variables,
                        QueryVariable.NUMBER: pull_request_number,
                        QueryVariable.THREAD_CURSOR: cursor,
                    },
                )
            ).pull_request
            page = pull_request.review_threads
            threads.extend(page.threads)
            if not page.page_info.has_next_page:
                break
            cursor = page.page_info.end_cursor
        return UpstreamPullRequestSnapshot.assemble(pull_request, threads)


@dataclass
class RestPullRequestReader(PullRequestSource):
    """
    Reads one upstream pull request's checks and review state over REST, which is what a
    Claude Code session's proxy answers once the upstream is attached to it.
    """

    client: RestClient
    """
    How REST requests reach GitHub.
    """

    upstream_repository: Repository
    """
    The repository the fork's pull requests are opened against.
    """

    fork_owner: str
    """
    The owner whose branches this reader will claim as its own.
    """

    @property
    def route(self) -> RepositoryRoute:
        """:return: The paths under the upstream."""
        return RepositoryRoute(self.upstream_repository)

    def resolve_pull_request_number(self, branch: str) -> int:
        """
        See :meth:`PullRequestSource.resolve_pull_request_number`.
        """
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
        """
        See :meth:`PullRequestSource.read_current_state`.
        """
        pull_request = RestPullRequest.from_json(
            self.client.get(self.route.pull_request(pull_request_number))
        )
        return UpstreamPullRequestSnapshot(
            number=pull_request.number,
            title=pull_request.title,
            url=pull_request.url,
            reviews=self._reviews(pull_request_number),
            threads=self._threads(pull_request_number),
            checks=CommitCheckReader(self.client, self.route).checks(
                pull_request.head.commit
            ),
        )

    def _reviews(self, pull_request_number: int) -> list[Review]:
        """
        :param pull_request_number: The pull request's number.
        :return: Every submitted review, oldest first.
        """
        return [
            Review.from_rest_json(entry)
            for page in self.client.get_pages(self.route.reviews(pull_request_number))
            for entry in page
        ]

    def _threads(self, pull_request_number: int) -> list[ReviewThread]:
        """
        Read the threads, then fill each in from the comments listed separately.

        :param pull_request_number: The pull request's number.
        :return: Every review thread, in the order the route returned them.
        """
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


class ReadSource(StrEnum):
    """
    The two APIs a pull request can be read through.
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
        client: GitHubApi,
        upstream_repository: Repository,
        fork_owner: str,
    ) -> PullRequestSource:
        """
        :param client: The client both readers go through.
        :param upstream_repository: The repository to read.
        :param fork_owner: Whose branches to claim.
        :return: The reader for this API.
        """
        if self is ReadSource.REST:
            return RestPullRequestReader(client, upstream_repository, fork_owner)
        return UpstreamPullRequestReader(client, upstream_repository, fork_owner)

    def writer(self, client: GitHubApi, repository: Repository) -> ReviewThreadWriter:
        """
        :param client: The client the writer goes through.
        :param repository: The repository whose review threads it writes.
        :return: The review thread writer for this API.
        """
        if self is ReadSource.REST:
            return RestReviewThreadWriter(client, repository)
        return GraphQLReviewThreadWriter(client, repository, client)
