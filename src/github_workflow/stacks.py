"""
Put one pull request on top of another in a native GitHub stack: retarget it at the
branch below when it targets something else, then create the stack or grow it.
"""

from __future__ import annotations

from dataclasses import dataclass

from basstler_domain_model.github.repository_client import (
    PullRequestBaseWriter,
    PullRequestReader,
    StackReader,
    StackWriter,
)
from basstler_domain_model.github.stack_models import Stack

from github_workflow.exceptions import StackContinuesAboveError

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
        below_branch = self.pull_requests.pull_request(below).head.branch
        above_base = self.pull_requests.pull_request(above).base
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
