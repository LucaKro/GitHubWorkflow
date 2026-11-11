"""
Putting one pull request on top of another in a native GitHub stack, and moving a stack
off a pull request whose work has landed.
"""

from __future__ import annotations

from dataclasses import dataclass

from domain_model.github.exceptions import StackContinuesAboveError
from domain_model.github.repository_client import StackHost
from domain_model.github.stack_models import Stack
from domain_model.github.vocabulary import PullRequestState

# %% placing a pull request


@dataclass(frozen=True)
class StackPlacement:
    """
    Puts pull requests on top of others in a repository's native stacks.
    """

    host: StackHost
    """
    The repository whose pull requests are stacked.
    """

    def place(self, below: int, above: int) -> Stack:
        """
        :param below: The pull request to build on.
        :param above: The pull request to put on top of it.
        :return: The stack holding both, *above* right on top of *below*. A stack in
            which only closed or merged pull requests sit on *below* is made again from
            its open ones and *above*.
        :raises StackContinuesAboveError: If other open pull requests already sit on
            *below*.
        """
        below_branch = self.host.pull_request(below).head.branch
        above_base = self.host.pull_request(above).base
        if above_base != below_branch:
            self.host.set_base(above, below_branch)
        stack = self.host.containing_stack(below)
        if stack is None:
            return self.host.create_stack([below, above])
        position = stack.numbers.index(below)
        on_top = stack.numbers[position + 1 :]
        if on_top[:1] == [above]:
            return stack
        if not on_top:
            return self.host.add_to_stack(stack, [above])
        self.refuse_open_on_top(below, on_top)
        self.host.unstack(stack)
        kept = [number for number in stack.numbers[:position] if self.is_open(number)]
        return self.host.create_stack([*kept, below, above])

    def check_placeable(self, below: int) -> None:
        """
        :param below: A pull request another is to be put on top of.
        :raises StackContinuesAboveError: If other open pull requests already sit on
            it.
        """
        stack = self.host.containing_stack(below)
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
        stack = self.host.containing_stack(done)
        if stack is None:
            return None
        position = stack.numbers.index(done)
        above = [
            number for number in stack.numbers[position + 1 :] if self.is_open(number)
        ]
        if not above:
            return None
        self.host.unstack(stack)
        self.host.set_base(above[0], base)
        if len(above) > 1:
            self.host.create_stack(above)
        return above[0]

    def is_open(self, number: int) -> bool:
        """
        :param number: A pull request.
        :return: Whether it is open.
        """
        return self.host.pull_request(number).state is PullRequestState.OPEN
