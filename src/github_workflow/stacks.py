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
from basstler_domain_model.github.vocabulary import PullRequestState

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
        :return: The stack holding both, *above* right on top of *below*. A stack in
            which only closed or merged pull requests sit on *below* is dissolved and
            made again from its open ones and *above*, since GitHub keeps those in it.
        :raises StackContinuesAboveError: If other open pull requests already sit on
            *below*.
        """
        below_branch = self.pull_requests.pull_request(below).head.branch
        above_base = self.pull_requests.pull_request(above).base
        if above_base != below_branch:
            self.retargeting.set_base(above, below_branch)
        stack = self.stacks.stack_of(below)
        if stack is None:
            return self.stacking.create_stack([below, above])
        position = stack.numbers.index(below)
        on_top = stack.numbers[position + 1 :]
        if on_top[:1] == [above]:
            return stack
        if not on_top:
            return self.stacking.add_to_stack(stack, [above])
        self.refuse_open_on_top(below, on_top)
        self.stacking.unstack(stack)
        kept = [number for number in stack.numbers[:position] if self.is_open(number)]
        return self.stacking.create_stack([*kept, below, above])

    def check_placeable(self, below: int) -> None:
        """
        :param below: A pull request another is to be put on top of.
        :raises StackContinuesAboveError: If other open pull requests already sit on
            it.
        """
        stack = self.stacks.stack_of(below)
        if stack is None:
            return
        self.refuse_open_on_top(below, stack.numbers[stack.numbers.index(below) + 1 :])

    def refuse_open_on_top(self, below: int, on_top: list[int]) -> None:
        """
        :param below: A pull request in a stack.
        :param on_top: The pull requests sitting on it in that stack.
        :raises StackContinuesAboveError: If one of them is open.
        """
        if any(self.is_open(number) for number in on_top):
            raise StackContinuesAboveError(below, tuple(on_top))

    def move_off(self, done: int, base: str) -> int | None:
        """
        Move what builds on a pull request whose work has landed onto the branch given.

        :param done: The pull request at the bottom of its stack.
        :param base: The branch the next one targets instead, the default branch.
        :return: The open pull request now targeting *base*, ``None`` when nothing open
            builds on *done*; the stack is made again from the open ones above.

        .. note:: The stack is dissolved first: GitHub refuses to change the base of a
           pull request in a stack.
        """
        stack = self.stacks.stack_of(done)
        if stack is None:
            return None
        position = stack.numbers.index(done)
        above = [
            number for number in stack.numbers[position + 1 :] if self.is_open(number)
        ]
        if not above:
            return None
        self.stacking.unstack(stack)
        self.retargeting.set_base(above[0], base)
        if len(above) > 1:
            self.stacking.create_stack(above)
        return above[0]

    def is_open(self, number: int) -> bool:
        """
        :param number: A pull request.
        :return: Whether it is open.
        """
        return self.pull_requests.pull_request(number).state is PullRequestState.OPEN
