"""
The reviews of a fork's pull request opened upstream, read directly where the upstream
is reached, and otherwise by the fork's Actions, which answer a request queued on the
notes branch with GitHub's answers saved there. Nothing is ever written upstream.

Usage on the runner: ``python -m github_workflow.upstream_reviews <requests directory>
<answers directory>``; answers every waiting request and removes it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Self

from domain_model.class_property import classproperty
from domain_model.git.revisions import BranchName
from domain_model.github.clients import GitHubReader
from domain_model.github.pull_request_models import UpstreamPullRequestSnapshot
from domain_model.github.readers import GraphQLReadSource
from domain_model.repository import Repository

from github_workflow.exceptions import ForwardedReadUnavailable
from github_workflow.forwarded_reads import (
    ForwardedReadAnswering,
    ForwardedReading,
    ForwardedRequest,
)
from github_workflow.workflow_templates import ForwardedSubject

if TYPE_CHECKING:
    from github_workflow.policy import WritePolicy

# %% requests


class UpstreamReviewKey(StrEnum):
    """
    The keys of a request, as the notes branch holds it.
    """

    UPSTREAM = "upstream"
    """
    The repository the fork was forked from, as ``owner/name``.
    """

    FORK_OWNER = "fork_owner"
    """
    The owner of the fork.
    """

    BRANCH = "branch"
    """
    The fork's branch.
    """


@dataclass(frozen=True)
class UpstreamReviewRequest(ForwardedRequest[UpstreamPullRequestSnapshot]):
    """
    A request for the reviews of the pull request a fork's branch has open upstream.
    """

    upstream: Repository
    """
    The repository the fork was forked from.
    """

    fork_owner: str
    """
    The owner of the fork, whose branch the pull request is opened from.
    """

    branch: BranchName
    """
    The fork's branch.
    """

    @classproperty
    def subject(cls) -> ForwardedSubject:
        return ForwardedSubject.UPSTREAM_REVIEWS

    def to_json(self) -> dict[str, Any]:
        return {
            UpstreamReviewKey.UPSTREAM: self.upstream.full_name,
            UpstreamReviewKey.FORK_OWNER: self.fork_owner,
            UpstreamReviewKey.BRANCH: self.branch,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any], name: str) -> Self:
        return cls(
            Repository.parse(data[UpstreamReviewKey.UPSTREAM]),
            data[UpstreamReviewKey.FORK_OWNER],
            BranchName(data[UpstreamReviewKey.BRANCH]),
            name=name,
        )

    def read(self, client: GitHubReader) -> UpstreamPullRequestSnapshot:
        """
        :return: The upstream pull request's reviews, threads and checks; see
            :meth:`ForwardedRequest.read`.
        :raises UpstreamPullRequestNotFound: If the branch has none upstream.
        """
        reader = GraphQLReadSource().reader(client, self.upstream, self.fork_owner)
        return reader.read_current_state(
            reader.resolve_pull_request_number(self.branch)
        )


# %% reading them


class UpstreamReviews(ABC):
    """
    Reads the pull request a fork's branch has open upstream.
    """

    @abstractmethod
    def read(
        self, request: UpstreamReviewRequest
    ) -> UpstreamPullRequestSnapshot | ForwardedReadUnavailable:
        """
        :param request: Which pull request.
        :return: Its reviews, threads and checks, or why they could not be read.
        """

    def read_work_branch_snapshot(
        self, upstream: Repository, policy: WritePolicy
    ) -> UpstreamPullRequestSnapshot | ForwardedReadUnavailable:
        """
        :param upstream: The repository the owner's was forked from.
        :param policy: The checkout and its work branch.
        :return: The reviews, threads and checks of the pull request the work branch
            has open upstream, or why they could not be read.
        """
        return self.read(
            UpstreamReviewRequest(
                upstream, policy.remote.repository.owner, policy.work_branch()
            )
        )


@dataclass(frozen=True)
class DirectUpstreamReviews(UpstreamReviews):
    """
    Reads it directly, its threads through GitHub's GraphQL API, which the person's own
    login reaches.
    """

    client: GitHubReader
    """
    How the reads reach GitHub.
    """

    def read(
        self, request: UpstreamReviewRequest
    ) -> UpstreamPullRequestSnapshot | ForwardedReadUnavailable:
        return request.read(self.client)


@dataclass(frozen=True)
class ForwardedUpstreamReviews(ForwardedReading, UpstreamReviews):
    """
    Has the fork's Actions read it, through a request queued on the notes branch.
    """


# %% answering them, on the runner


def main() -> None:
    """
    Answer the requests waiting in the directory the command line names.
    """
    ForwardedReadAnswering.answer_command_line(UpstreamReviewRequest)


if __name__ == "__main__":
    main()
