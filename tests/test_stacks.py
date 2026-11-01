"""
Tests for :mod:`github_workflow.stacks`: putting a pull request on top of another in a
native stack, and only in the owner's repository.
"""

from __future__ import annotations

import subprocess
import sys

import pytest
from basstler_domain_model.github.stack_models import Stack

import github_workflow.stacks
from github_workflow.exceptions import NoOwnedRemoteError, StackContinuesAboveError
from github_workflow.stacks import StackCommand, StackPlacement

from .repositories_by_owner import RepositoriesByOwner
from .stacked_pull_requests import StackedPullRequestsInMemory

# %% helpers


def placement(repository: StackedPullRequestsInMemory) -> StackPlacement:
    """:param repository: The pull requests and stacks in memory.
    :return: A placement working on them."""
    return StackPlacement(repository, repository, repository, repository)


def existing_stack(repository: StackedPullRequestsInMemory, *numbers: int) -> Stack:
    """
    :param repository: The pull requests and stacks in memory.
    :param numbers: The stack's pull requests, bottom first.
    :return: The stack, added to *repository*.
    """
    stack = Stack(7, "main", True, repository.stacked(numbers))
    repository.existing_stacks.append(stack)
    return stack


# %% retargeting


def test_a_pull_request_is_retargeted_at_the_branch_below():
    repository = StackedPullRequestsInMemory({1: "main", 2: "main"})

    placement(repository).place(1, 2)

    assert repository.bases[2] == repository.branch_of(1)


def test_a_pull_request_already_targeting_the_branch_below_is_left_alone():
    repository = StackedPullRequestsInMemory(
        {1: "main", 2: StackedPullRequestsInMemory.branch_of(1)}
    )

    placement(repository).place(1, 2)

    assert not [write for write in repository.writes if write.startswith("set_base")]


# %% the stack


def test_two_pull_requests_in_no_stack_form_a_new_one():
    repository = StackedPullRequestsInMemory({1: "main", 2: "main"})

    stack = placement(repository).place(1, 2)

    assert stack.numbers == [1, 2]


def test_a_pull_request_goes_on_top_of_the_stack_whose_top_it_builds_on():
    repository = StackedPullRequestsInMemory({1: "main", 2: "main", 3: "main"})
    existing_stack(repository, 1, 2)

    stack = placement(repository).place(2, 3)

    assert stack.numbers == [1, 2, 3]


def test_placing_a_pull_request_where_it_already_is_writes_nothing():
    repository = StackedPullRequestsInMemory(
        {1: "main", 2: StackedPullRequestsInMemory.branch_of(1)}
    )
    existing = existing_stack(repository, 1, 2)

    assert placement(repository).place(1, 2) == existing
    assert repository.writes == []


def test_a_pull_request_others_already_build_on_is_not_built_on_again():
    repository = StackedPullRequestsInMemory({1: "main", 2: "main", 3: "main"})
    existing_stack(repository, 1, 2)

    with pytest.raises(StackContinuesAboveError):
        placement(repository).place(1, 3)


# %% only the owner's repository


def test_stacking_in_somebody_else_s_repository_is_refused_before_any_call(
    repositories: RepositoriesByOwner, foreign_url: str
):
    checkout = repositories.clone(foreign_url, "theirs")

    finished = subprocess.run(
        [
            sys.executable,
            "-m",
            github_workflow.stacks.__name__,
            StackCommand.ON,
            "1",
            "2",
        ],
        cwd=checkout.root,
        capture_output=True,
        text=True,
    )

    assert finished.returncode != 0
    assert NoOwnedRemoteError.__name__ in finished.stderr
