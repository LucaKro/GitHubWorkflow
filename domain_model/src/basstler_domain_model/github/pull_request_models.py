"""
Models of a pull request and the checks reported against its head commit, as GitHub's
GraphQL API returns them, and the snapshot a report is rendered from.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from basstler_domain_model.github.exceptions import (
    GraphQLDataMissingError,
    GraphQLErrorsReturned,
)
from basstler_domain_model.github.review_models import (
    BranchPullRequest,
    Review,
    ReviewThread,
    ReviewThreadPage,
)
from basstler_domain_model.github.vocabulary import (
    CheckContextType,
    CheckOutcome,
    JSONModel,
    PullRequestJSONKey,
    RestJSONKey,
    RollupState,
)

# %% models mirroring the pull request


@dataclass(frozen=True)
class CheckResult(JSONModel):
    """
    One check reported against the pull request's head commit.
    """

    name: str
    """
    What the check calls itself.
    """

    outcome: CheckOutcome
    """
    Where the check stands.
    """

    url: str
    """
    Where the check's own output is, empty when it reported none.
    """

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> CheckResult:
        """
        Read one check out of a rollup context node.

        :param data: The node to read.
        :return: The parsed check.
        :raises UnrecognisedGitHubValueError: If the node is neither shape a rollup can
            hold, or its outcome is one GitHub added later.
        """
        if (
            CheckContextType.from_value(data[PullRequestJSONKey.TYPE_NAME])
            is CheckContextType.CHECK_RUN
        ):
            conclusion = data[PullRequestJSONKey.CONCLUSION]
            return cls(
                name=data[PullRequestJSONKey.NAME],
                outcome=(
                    CheckOutcome.from_name(conclusion)
                    if conclusion
                    else CheckOutcome.PENDING
                ),
                url=data[PullRequestJSONKey.DETAILS_URL] or "",
            )
        return cls(
            name=data[PullRequestJSONKey.CONTEXT],
            outcome=CheckOutcome.from_name(data[PullRequestJSONKey.STATE]),
            url=data[PullRequestJSONKey.TARGET_URL] or "",
        )

    @classmethod
    def from_check_run_json(cls, data: dict[str, Any]) -> CheckResult:
        """
        Read a check run as REST lists it, whose conclusion is null until it finishes.

        :param data: The check run object.
        :return: The parsed check.
        """
        conclusion = data[RestJSONKey.CONCLUSION]
        return cls(
            name=data[RestJSONKey.NAME],
            outcome=(
                CheckOutcome.from_name(conclusion.upper())
                if conclusion
                else CheckOutcome.PENDING
            ),
            url=data[RestJSONKey.DETAILS_URL] or "",
        )

    @classmethod
    def from_commit_status_json(cls, data: dict[str, Any]) -> CheckResult:
        """
        Read a status posted through the commit-status API.

        :param data: The status object.
        :return: The parsed check.
        """
        return cls(
            name=data[RestJSONKey.CONTEXT],
            outcome=CheckOutcome.from_name(data[RestJSONKey.STATE].upper()),
            url=data[RestJSONKey.TARGET_URL] or "",
        )

    @property
    def succeeded(self) -> bool:
        """:return: Whether this check reported success."""
        return self.outcome is CheckOutcome.SUCCESS


@dataclass(frozen=True)
class CheckStatus(JSONModel):
    """
    Every check reported against the pull request, with GitHub's verdict over them.
    """

    state: RollupState
    """
    The verdict GitHub computed over all of them.
    """

    results: list[CheckResult]
    """
    Every check, in the order GitHub returned them.
    """

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> CheckStatus:
        """
        Read the rollup out of a ``statusCheckRollup`` object.

        :param data: The rollup to read.
        :return: The parsed status.
        """
        return cls(
            state=RollupState.from_name(data[PullRequestJSONKey.STATE]),
            results=PullRequestJSONKey.CONTEXTS.read_list(data, CheckResult),
        )

    @classmethod
    def over(cls, results: list[CheckResult]) -> CheckStatus | None:
        """
        Gather checks read one by one, computing the verdict GitHub would give them.

        :param results: Every check, in the order to report them.
        :return: The status, or ``None`` when nothing has reported.
        """
        if not results:
            return None
        return cls(
            state=RollupState.over([result.outcome for result in results]),
            results=results,
        )

    @property
    def unsuccessful(self) -> list[CheckResult]:
        """:return: The checks that did not report success."""
        return [result for result in self.results if not result.succeeded]


@dataclass(frozen=True)
class Commit(JSONModel):
    """
    A commit, carrying the checks reported against it.
    """

    checks: CheckStatus | None
    """
    The checks reported against this commit, absent when none have reported.
    """

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Commit:
        """
        Read a ``commit`` object, whose rollup GitHub leaves null while nothing has
        reported against it.

        :param data: The object to read.
        :return: The parsed commit.
        """
        rollup = data[PullRequestJSONKey.STATUS_CHECK_ROLLUP]
        return cls(checks=CheckStatus.from_json(rollup) if rollup else None)


@dataclass(frozen=True)
class PullRequestCommit(JSONModel):
    """
    One entry of a pull request's commit list, which wraps the commit itself.
    """

    commit: Commit
    """
    The commit this entry stands for.
    """

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> PullRequestCommit:
        """
        Read one ``commits`` node.

        :param data: The node to read.
        :return: The parsed entry.
        """
        return cls(commit=Commit.from_json(data[PullRequestJSONKey.COMMIT]))


@dataclass(frozen=True)
class PullRequest(JSONModel):
    """
    One upstream pull request, as a single page of the review-threads query reads it.
    """

    number: int
    """
    Its number on the upstream repository.
    """

    title: str
    """
    Its title.
    """

    url: str
    """
    Its web URL.
    """

    commits: list[PullRequestCommit]
    """
    The commits the query selected, which is the head commit alone.
    """

    reviews: list[Review]
    """
    Every submitted review, oldest first.
    """

    review_threads: ReviewThreadPage
    """
    The page of review threads this response carried.
    """

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> PullRequest:
        """
        Read a ``pullRequest`` object.

        :param data: The object to read.
        :return: The parsed pull request.
        """
        return cls(
            number=data[PullRequestJSONKey.NUMBER],
            title=data[PullRequestJSONKey.TITLE],
            url=data[PullRequestJSONKey.URL],
            commits=PullRequestJSONKey.COMMITS.read_list(data, PullRequestCommit),
            reviews=PullRequestJSONKey.REVIEWS.read_list(data, Review),
            review_threads=ReviewThreadPage.from_json(
                data[PullRequestJSONKey.REVIEW_THREADS]
            ),
        )

    @property
    def checks(self) -> CheckStatus | None:
        """
        The checks reported against the head commit.

        GitHub hangs the rollup off the commit rather than the pull request.

        :return: The checks, or ``None`` when nothing has reported.
        """
        if not self.commits:
            return None
        return self.commits[-1].commit.checks


@dataclass(frozen=True)
class UpstreamPullRequestSnapshot:
    """
    Everything read from one upstream pull request in a single run.
    """

    number: int
    """
    The pull request's number on the upstream repository.
    """

    title: str
    """
    The pull request's title.
    """

    url: str
    """
    The pull request's web URL.
    """

    reviews: list[Review]
    """
    Every submitted review, oldest first.
    """

    threads: list[ReviewThread]
    """
    Every review thread, in the order GitHub returned them.
    """

    checks: CheckStatus | None
    """
    The checks reported against the head commit, absent when none have reported.
    """

    @classmethod
    def assemble(
        cls, pull_request: PullRequest, threads: list[ReviewThread]
    ) -> UpstreamPullRequestSnapshot:
        """
        Combine a parsed pull request with every thread its pages carried.

        :param pull_request: The pull request, as the last page read it.
        :param threads: Every thread gathered across the paged reads.
        :return: The assembled snapshot.
        """
        return cls(
            number=pull_request.number,
            title=pull_request.title,
            url=pull_request.url,
            reviews=pull_request.reviews,
            threads=threads,
            checks=pull_request.checks,
        )

    @property
    def unresolved_threads(self) -> list[ReviewThread]:
        """:return: The threads still awaiting action."""
        return [thread for thread in self.threads if not thread.is_resolved]


@dataclass(frozen=True)
class PullRequestForBranchResult(JSONModel):
    """
    What :attr:`GraphQLDocument.PULL_REQUEST_FOR_BRANCH` returns.
    """

    pull_requests: list[BranchPullRequest]
    """
    Every pull request the head-branch search matched, newest first.
    """

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> PullRequestForBranchResult:
        """
        Read the query's ``data``, whose ``repository`` object selects nothing else.

        :param data: The response's ``data`` object.
        :return: The parsed result.
        """
        return cls(
            pull_requests=PullRequestJSONKey.PULL_REQUESTS.read_list(
                data[PullRequestJSONKey.REPOSITORY], BranchPullRequest
            )
        )


@dataclass(frozen=True)
class ReviewThreadsPageResult(JSONModel):
    """
    What :attr:`GraphQLDocument.REVIEW_THREADS_PAGE` returns.
    """

    pull_request: PullRequest
    """
    The pull request, carrying one page of its review threads.
    """

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> ReviewThreadsPageResult:
        """
        Read the query's ``data``, whose ``repository`` object selects nothing else.

        :param data: The response's ``data`` object.
        :return: The parsed result.
        """
        return cls(
            pull_request=PullRequest.from_json(
                data[PullRequestJSONKey.REPOSITORY][PullRequestJSONKey.PULL_REQUEST]
            )
        )


@dataclass(frozen=True)
class GraphQLResponse:
    """
    A parsed GraphQL response envelope.
    """

    data: dict[str, Any] | None
    """
    The response's ``data`` member, absent when the query failed outright.
    """

    errors: list[str] = field(default_factory=list)
    """
    Every message from an ``errors`` array, empty on success.
    """

    @classmethod
    def from_json(cls, text: str) -> GraphQLResponse:
        """
        Parse a response body.

        :param text: The raw JSON GitHub returned.
        :return: The parsed envelope.
        """
        body = json.loads(text)
        return cls(
            data=body.get(PullRequestJSONKey.DATA),
            errors=[
                error[PullRequestJSONKey.MESSAGE]
                for error in body.get(PullRequestJSONKey.ERRORS, [])
            ],
        )

    def result(self) -> dict[str, Any]:
        """
        :return: The query's result.
        :raises GraphQLErrorsReturned: If GitHub reported errors instead.
        :raises GraphQLDataMissingError: If GitHub reported neither data nor errors.
        """
        if self.errors:
            raise GraphQLErrorsReturned(self.errors)
        if self.data is None:
            raise GraphQLDataMissingError()
        return self.data
