"""
Pull requests and native stacks kept in memory, standing in for a repository's, and
recording every write made to them.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from basstler_domain_model.github.pull_request_fields import (
    PullRequestHeadKey,
    PullRequestPayload,
)
from basstler_domain_model.github.repository_client import (
    PullRequestBaseWriter,
    PullRequestOpener,
    PullRequestReader,
    StackReader,
    StackWriter,
)
from basstler_domain_model.github.stack_models import Stack, StackedPullRequest
from basstler_domain_model.github.vocabulary import PullRequestState, RestJSONKey

# %% the stand-in


@dataclass(frozen=True)
class StackedPullRequestsInMemory(
    PullRequestReader, PullRequestBaseWriter, StackReader, StackWriter
):
    """
    A repository's pull requests, each a branch and the base it targets, and its stacks.
    """

    bases: dict[int, str]
    """
    Each pull request's base, by number; its own branch is ``branch-<number>``.
    """

    existing_stacks: list[Stack] = field(default_factory=list)
    """
    The stacks the repository holds.
    """

    writes: list[str] = field(default_factory=list)
    """
    Every write made, described in a word and its arguments.
    """

    @staticmethod
    def branch_of(number: int) -> str:
        """:param number: A pull request.
        :return: Its branch."""
        return f"branch-{number}"

    def stacked(self, numbers: Sequence[int]) -> list[StackedPullRequest]:
        """:param numbers: Pull requests, bottom first.
        :return: Them as a stack holds them."""
        return [
            StackedPullRequest(
                number, PullRequestState.OPEN, True, self.branch_of(number)
            )
            for number in numbers
        ]

    def open_pull_requests(self) -> list[PullRequestPayload]:
        return [self.pull_request(number) for number in self.bases]

    def pull_request(self, number: int) -> PullRequestPayload:
        return {
            RestJSONKey.NUMBER: number,
            RestJSONKey.HEAD: {
                PullRequestHeadKey.REFERENCE: self.branch_of(number),
                PullRequestHeadKey.HEAD_REPOSITORY: None,
                RestJSONKey.SHA: "0" * 40,
            },
            RestJSONKey.BASE: {PullRequestHeadKey.REFERENCE: self.bases[number]},
        }

    def set_base(self, number: int, branch: str) -> None:
        self.writes.append(f"set_base {number} {branch}")
        self.bases[number] = branch

    def stacks(self) -> list[Stack]:
        return list(self.existing_stacks)

    def stack(self, number: int) -> Stack:
        return next(stack for stack in self.existing_stacks if stack.number == number)

    def stack_of(self, pull_request: int) -> Stack | None:
        return next(
            (stack for stack in self.existing_stacks if pull_request in stack.numbers),
            None,
        )

    def create_stack(self, pull_requests: Sequence[int]) -> Stack:
        self.writes.append(f"create_stack {list(pull_requests)}")
        return Stack(1, "main", True, self.stacked(pull_requests))

    def add_to_stack(self, stack: Stack, pull_requests: Sequence[int]) -> Stack:
        self.writes.append(f"add_to_stack {stack.number} {list(pull_requests)}")
        return Stack(
            stack.number,
            stack.base,
            True,
            stack.pull_requests + self.stacked(pull_requests),
        )

    def unstack(self, stack: Stack) -> Stack | None:
        self.writes.append(f"unstack {stack.number}")
        return None


# %% opening drafts too


@dataclass(frozen=True)
class DraftsAndStacksInMemory(StackedPullRequestsInMemory, PullRequestOpener):
    """
    The stand-in, also opening draft pull requests, each numbered after the highest.
    """

    def open_draft(self, head: str, base: str, title: str, body: str) -> int:
        number = max(self.bases, default=0) + 1
        self.writes.append(f"open_draft {head} {base}")
        self.bases[number] = base
        return number
