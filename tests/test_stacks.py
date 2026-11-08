"""
Tests for :mod:`github_workflow.stacks`: putting a pull request on top of another in a
native stack, and only in the owner's repository.
"""

from __future__ import annotations

import subprocess
import sys

import pytest
from basstler_domain_model.git.commands import RemoteName
from basstler_domain_model.github.stack_models import Stack

import github_workflow
from github_workflow.exceptions import NoOwnedRemoteError
from github_workflow.command_line import (
    StackSubcommand,
    WorkflowCommand,
)
from github_workflow.settings import WorkflowSettings
from basstler_domain_model.github.exceptions import StackContinuesAboveError
from basstler_domain_model.github.stack_placement import StackPlacement

from .repositories_by_owner import RepositoriesByOwner
from .stacked_pull_requests import DraftsInMemory, StackedPullRequestsInMemory

# %% helpers


def placement(repository: StackedPullRequestsInMemory) -> StackPlacement:
    """:param repository: The pull requests and stacks in memory.
    :return: A placement working on them."""
    return StackPlacement(repository)


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


def test_a_stack_held_above_only_by_closed_pull_requests_is_made_again():
    """
    GitHub keeps closed pull requests in their stack, so the replacement of one takes
    its place in a stack made from the open ones.
    """
    repository = DraftsInMemory(
        {1: "main", 2: "main", 3: "main", 4: "main", 5: "main"},
        closed=frozenset({3, 4}),
    )
    existing = existing_stack(repository, 1, 2, 3, 4)

    stack = placement(repository).place(2, 5)

    assert stack.numbers == [1, 2, 5]
    assert f"unstack {existing.number}" in repository.writes


def test_a_pull_request_others_already_build_on_is_not_built_on_again():
    repository = StackedPullRequestsInMemory({1: "main", 2: "main", 3: "main"})
    existing_stack(repository, 1, 2)

    with pytest.raises(StackContinuesAboveError):
        placement(repository).place(1, 3)


def test_a_pull_request_others_already_build_on_is_found_unplaceable_first():
    repository = StackedPullRequestsInMemory({1: "main", 2: "main"})
    existing_stack(repository, 1, 2)

    with pytest.raises(StackContinuesAboveError):
        placement(repository).check_placeable(1)

    assert repository.writes == []


def test_the_top_of_a_stack_is_placeable():
    repository = StackedPullRequestsInMemory({1: "main", 2: "main"})
    existing_stack(repository, 1, 2)

    placement(repository).check_placeable(2)

    assert repository.writes == []


# %% only the owner's repository


# %% moving a stack off a pull request whose work landed


def test_the_pull_request_above_a_done_one_moves_onto_the_default_branch():
    repository = StackedPullRequestsInMemory(
        {1: "main", 2: StackedPullRequestsInMemory.branch_of(1), 3: "branch-2"}
    )
    existing = existing_stack(repository, 1, 2, 3)

    moved = placement(repository).move_off(1, "main")

    assert (moved, repository.writes) == (
        2,
        ["set_base 2 main", f"unstack {existing.number}", "create_stack [2, 3]"],
    )


def test_a_single_pull_request_left_above_forms_no_stack():
    repository = StackedPullRequestsInMemory(
        {1: "main", 2: StackedPullRequestsInMemory.branch_of(1)}
    )
    existing = existing_stack(repository, 1, 2)

    moved = placement(repository).move_off(1, "main")

    assert (moved, repository.writes) == (
        2,
        ["set_base 2 main", f"unstack {existing.number}"],
    )


def test_a_done_pull_request_in_no_stack_moves_nothing():
    repository = StackedPullRequestsInMemory({1: "main"})

    assert (placement(repository).move_off(1, "main"), repository.writes) == (None, [])


def test_stacking_in_somebody_else_s_repository_is_refused_before_any_call(
    repositories: RepositoriesByOwner, foreign_url: str
):
    checkout = repositories.clone(foreign_url, "theirs")

    finished = subprocess.run(
        [
            sys.executable,
            "-m",
            github_workflow.__name__,
            WorkflowCommand.STACK,
            StackSubcommand.ON,
            "1",
            "2",
        ],
        cwd=checkout.root,
        capture_output=True,
        text=True,
    )

    refusal = NoOwnedRemoteError(WorkflowSettings().owner, (RemoteName.ORIGIN,))
    assert (finished.returncode, finished.stderr) == (
        1,
        f"github-workflow: {refusal}\n",
    )
