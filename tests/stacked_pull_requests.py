"""
Pull requests and native stacks kept in memory, standing in for a repository's, and
recording every write made to them.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace

from basstler_domain_model.github.repository_client import (
    PullRequestOpener,
    PullRequestWriter,
    StackHost,
)
from basstler_domain_model.github.rest_models import RestPullRequest
from basstler_domain_model.github.stack_models import Stack, StackedPullRequest
from basstler_domain_model.github.vocabulary import PullRequestState

from .pull_requests import pull_request

# %% the stand-in


@dataclass(frozen=True)
class StackedPullRequestsInMemory(StackHost):
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

    def open_pull_requests(self) -> list[RestPullRequest]:
        return [self.pull_request(number) for number in self.bases]

    def pull_request(self, number: int) -> RestPullRequest:
        return pull_request(number, self.branch_of(number), base=self.bases[number])

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

    bodies: dict[int, str] = field(default_factory=dict)
    """
    The description each draft was opened with, by its number.
    """

    def open_draft(self, head: str, base: str, title: str, body: str) -> int:
        number = max(self.bases, default=0) + 1
        self.writes.append(f"open_draft {head} {base}")
        self.bases[number] = base
        self.bodies[number] = body
        return number


# %% rewriting drafts too


@dataclass(frozen=True)
class DraftsInMemory(DraftsAndStacksInMemory, PullRequestWriter):
    """
    The stand-in, with pull requests that are drafts or not, open or closed, whose
    descriptions can be rewritten.
    """

    drafts: frozenset[int] = frozenset()
    """
    The pull requests that are drafts.
    """

    closed: frozenset[int] = frozenset()
    """
    The pull requests that are closed.
    """

    def pull_request(self, number: int) -> RestPullRequest:
        state = (
            PullRequestState.CLOSED if number in self.closed else PullRequestState.OPEN
        )
        return replace(
            super().pull_request(number), draft=number in self.drafts, state=state
        )

    def replace_labels(self, number: int, labels: Sequence[str]) -> None:
        self.writes.append(f"replace_labels {number}")

    def add_comment(self, number: int, body: str) -> str:
        self.writes.append(f"add_comment {number}")
        return ""

    def set_description(self, number: int, body: str) -> None:
        self.writes.append(f"set_description {number} {body}")
