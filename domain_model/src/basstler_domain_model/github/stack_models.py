"""
Models of GitHub's native stacks of pull requests, as the Stacks REST API returns them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from basstler_domain_model.github.vocabulary import (
    JSONModel,
    PullRequestState,
    RestJSONKey,
)

# %% models mirroring the Stacks REST API


@dataclass(frozen=True)
class StackedPullRequest(JSONModel):
    """
    One pull request in a stack.
    """

    number: int
    """
    Its number in the repository.
    """

    state: PullRequestState
    """
    Where it stands, merged told apart from closed by its merge time.
    """

    draft: bool
    """
    Whether it is still a draft.
    """

    branch: str
    """
    The branch it merges, which the pull request above it targets.
    """

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> StackedPullRequest:
        """
        Read one entry of a stack's pull requests.

        :param data: The entry to read.
        :return: The parsed pull request.
        """
        return cls(
            number=data[RestJSONKey.NUMBER],
            state=(
                PullRequestState.MERGED
                if data[RestJSONKey.MERGED_AT]
                else PullRequestState.from_value(data[RestJSONKey.STATE])
            ),
            draft=data[RestJSONKey.DRAFT],
            branch=data[RestJSONKey.HEAD][RestJSONKey.REFERENCE],
        )


@dataclass(frozen=True)
class Stack(JSONModel):
    """
    A stack of pull requests, each targeting the branch of the one below it, which
    GitHub retargets as the ones below land.
    """

    number: int
    """
    Its number in the repository, which addresses it.
    """

    base: str
    """
    The branch the bottom pull request targets.
    """

    open: bool
    """
    Whether the stack is still open.
    """

    pull_requests: list[StackedPullRequest]
    """
    Its pull requests, bottom first.
    """

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Stack:
        """
        Read a stack.

        :param data: The stack to read.
        :return: The parsed stack.
        """
        return cls(
            number=data[RestJSONKey.NUMBER],
            base=data[RestJSONKey.BASE][RestJSONKey.REFERENCE],
            open=data[RestJSONKey.OPEN],
            pull_requests=[
                StackedPullRequest.from_json(entry)
                for entry in data[RestJSONKey.PULL_REQUESTS]
            ],
        )

    @property
    def numbers(self) -> list[int]:
        """:return: Its pull requests' numbers, bottom first."""
        return [pull_request.number for pull_request in self.pull_requests]
