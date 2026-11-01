"""
Put one pull request on top of another in a native GitHub stack: retarget it at the
branch below when it targets something else, then create the stack or grow it.

Usage: ``python -m github_workflow.stacks on <below> <above>``
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from basstler_domain_model.github.pull_request_fields import (
    PullRequestField,
    PullRequestHead,
)
from basstler_domain_model.github.repository_client import (
    GitHubRepository,
    PullRequestBaseWriter,
    PullRequestReader,
    StackReader,
    StackWriter,
)
from basstler_domain_model.github.stack_models import Stack

from github_workflow.checkout import ProjectCheckout
from github_workflow.credential import GitHubToken
from github_workflow.exceptions import StackContinuesAboveError
from basstler_domain_model.commands import CommandRunner
from github_workflow.remotes import OwnedRemotes
from github_workflow.settings import WorkflowSettings

# %% vocabulary


class StackCommand(StrEnum):
    """
    What ``python -m github_workflow.stacks`` does.
    """

    ON = "on"
    """
    Put the second pull request on top of the first.
    """


# %% placing a pull request


@dataclass(frozen=True)
class StackPlacement:
    """
    Puts pull requests on top of others in native stacks, through the interfaces that
    read and write them.
    """

    pull_requests: PullRequestReader
    """
    Reads the pull requests.
    """

    retargeting: PullRequestBaseWriter
    """
    Points a pull request at another branch.
    """

    stacks: StackReader
    """
    Reads the stacks.
    """

    stacking: StackWriter
    """
    Creates and grows stacks.
    """

    def place(self, below: int, above: int) -> Stack:
        """
        :param below: The pull request to build on.
        :param above: The pull request to put on top of it.
        :return: The stack holding both, *above* right on top of *below*.
        :raises StackContinuesAboveError: If other pull requests already sit on *below*.
        """
        below_branch = PullRequestHead.from_record(
            self.pull_requests.pull_request(below), below
        ).branch
        above_base = PullRequestField.BASE.read(
            self.pull_requests.pull_request(above), above
        )
        if above_base != below_branch:
            self.retargeting.set_base(above, below_branch)
        stack = self.stacks.stack_of(below)
        if stack is None:
            return self.stacking.create_stack([below, above])
        on_top = stack.numbers[stack.numbers.index(below) + 1 :]
        if on_top[:1] == [above]:
            return stack
        if on_top:
            raise StackContinuesAboveError(below, tuple(on_top))
        return self.stacking.add_to_stack(stack, [above])


# %% entry point


def main() -> None:
    """
    Place the pull request the command line names, and print the stack it is in.
    """
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("command", choices=list(StackCommand))
    parser.add_argument("below", type=int, help="the pull request to build on")
    parser.add_argument("above", type=int, help="the pull request to put on top")
    arguments = parser.parse_args()
    checkout = ProjectCheckout.containing(Path.cwd())
    remote = OwnedRemotes.read(checkout.git, WorkflowSettings()).chosen
    github = GitHubRepository(
        remote.repository, GitHubToken(CommandRunner(checkout.root)).find()
    )
    stack = StackPlacement(github, github, github, github).place(
        arguments.below, arguments.above
    )
    layers = " <- ".join(
        f"#{pull_request.number} ({pull_request.branch})"
        for pull_request in stack.pull_requests
    )
    print(
        f"github-workflow: stack {stack.number} on {stack.base} in "
        f"{remote.repository.full_name}: {layers}"
    )


if __name__ == "__main__":
    main()
