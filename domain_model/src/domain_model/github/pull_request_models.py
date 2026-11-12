"""
The checks reported against a pull request's head commit, the snapshot a report is
rendered from, and GraphQL's answer envelope.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from domain_model.github.exceptions import (
    GraphQLDataMissingError,
    GraphQLErrorsReturned,
)
from domain_model.github.number_links import HasNumberLink
from domain_model.github.review_models import Review, ReviewThread
from domain_model.github.vocabulary import (
    CheckOutcome,
    PullRequestJSONKey,
    RestJSONKey,
    RollupState,
)

# %% models mirroring the pull request


@dataclass(frozen=True)
class CheckResult:
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
class CheckStatus:
    """
    Every check reported against the pull request, with the verdict over them.
    """

    state: RollupState
    """
    The verdict over all of them, as GitHub gives it.
    """

    results: list[CheckResult]
    """
    Every check, in the order GitHub returned them.
    """

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
class UpstreamPullRequestSnapshot(HasNumberLink):
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

    @property
    def unresolved_threads(self) -> list[ReviewThread]:
        """:return: The threads still awaiting action."""
        return [thread for thread in self.threads if not thread.is_resolved]


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
