"""
The errors the workflow's commands end in.
"""

from __future__ import annotations

from dataclasses import dataclass

from basstler_domain_model.exceptions import DataclassException

# %% whose repository


@dataclass
class NoOwnedRemoteError(DataclassException, LookupError):
    """
    Raised when no remote of the checkout points at a repository the owner owns.
    """

    owner: str
    """
    The account whose repositories alone are written to.
    """

    remote_names: tuple[str, ...]
    """
    Every remote the checkout has.
    """

    def error_message(self) -> str:
        remotes = ", ".join(self.remote_names) or "none"
        return f"no remote points at a repository of {self.owner} (remotes: {remotes})"

    def suggest_correction(self) -> str:
        return f"Add a remote for {self.owner}'s fork or repository, and work there."


@dataclass
class AmbiguousOwnedRemoteError(DataclassException, LookupError):
    """
    Raised when several remotes point at the owner's repositories and none is
    ``origin``.
    """

    owner: str
    """
    The account whose repositories alone are written to.
    """

    remote_names: tuple[str, ...]
    """
    The remotes that point at the owner's repositories.
    """

    def error_message(self) -> str:
        return (
            f"several remotes point at {self.owner}'s repositories "
            f"({', '.join(self.remote_names)}) and none is origin"
        )

    def suggest_correction(self) -> str:
        return "Rename the one to work with to origin."


# %% saving notes


@dataclass
class NotesBlockMissingError(DataclassException, LookupError):
    """
    Raised when saving finds no notes block in ``CLAUDE.local.md``.
    """

    document: str
    """
    The file that was read.
    """

    def error_message(self) -> str:
        return f"{self.document} holds no github-workflow notes block"

    def suggest_correction(self) -> str:
        return "Start a session first, which writes the block, then edit inside it."


# %% stacking


@dataclass
class StackContinuesAboveError(DataclassException, ValueError):
    """
    Raised when a pull request is to go on top of one that other pull requests in its
    stack already build on.
    """

    below: int
    """
    The pull request that was to be built on.
    """

    above: tuple[int, ...]
    """
    The pull requests the stack already holds above it.
    """

    def error_message(self) -> str:
        holders = ", ".join(f"#{number}" for number in self.above)
        return f"#{self.below} already has {holders} stacked on it; a stack is a single line"

    def suggest_correction(self) -> str:
        return "Stack the pull request on the top of that stack instead."
