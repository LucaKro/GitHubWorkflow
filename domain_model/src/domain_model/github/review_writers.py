"""
Writing to a pull request's review threads: replying through REST, which every place
reaches, and resolving through whichever API the place it runs in reaches.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from domain_model.github.clients import GraphQLClient, RestWriter
from domain_model.github.review_models import ReviewThread
from domain_model.github.routes import RepositoryRoute
from domain_model.github.vocabulary import GraphQLDocument, QueryVariable, RestJSONKey
from domain_model.repository import Repository

# %% writing


@dataclass(frozen=True)
class ReviewThreadWriter(ABC):
    """
    Replies to and resolves the review threads of one repository's pull requests.
    """

    rest: RestWriter
    """
    Sends the REST calls.
    """

    repository: Repository
    """
    The repository the pull requests are on.
    """

    @property
    def route(self) -> RepositoryRoute:
        """
        The repository's routes.
        """
        return RepositoryRoute(self.repository)

    def reply(self, number: int, thread: ReviewThread, body: str) -> str:
        """
        :param number: The pull request.
        :param thread: One of its review threads.
        :param body: The reply.
        :return: The reply's URL.
        """
        first = thread.comments[0].database_identifier
        created = self.rest.request(
            "POST",
            self.route.review_comment_replies(number, first),
            {RestJSONKey.BODY: body},
        )
        return str(created[RestJSONKey.HTML_URL])

    @abstractmethod
    def resolve(self, number: int, thread: ReviewThread) -> None:
        """
        Mark a review thread resolved.

        :param number: The pull request.
        :param thread: One of its review threads.
        """


@dataclass(frozen=True)
class RestReviewThreadWriter(ReviewThreadWriter):
    """
    Resolves through the route a Claude Code cloud session's proxy offers in place of
    GraphQL, naming the thread by its first comment.
    """

    def resolve(self, number: int, thread: ReviewThread) -> None:
        first = thread.comments[0].database_identifier
        self.rest.request("POST", self.route.thread_resolution(number, first), {})


@dataclass(frozen=True)
class GraphQLReviewThreadWriter(ReviewThreadWriter):
    """
    Resolves through GraphQL, which a runner or a developer's own machine reaches,
    naming the thread by its node identifier.
    """

    graphql: GraphQLClient
    """
    Sends the GraphQL mutation.
    """

    def resolve(self, number: int, thread: ReviewThread) -> None:
        self.graphql.execute(
            GraphQLDocument.RESOLVE_REVIEW_THREAD.read(),
            {QueryVariable.THREAD_ID: thread.identifier},
        )
