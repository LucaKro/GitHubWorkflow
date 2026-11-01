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


# %% writing on a work branch


@dataclass
class DetachedHeadError(DataclassException, RuntimeError):
    """
    Raised when a write needs a work branch and none is checked out.
    """

    def error_message(self) -> str:
        return "no branch is checked out"

    def suggest_correction(self) -> str:
        return "Start a work branch or switch to one first."


@dataclass
class DefaultBranchWriteError(DataclassException, RuntimeError):
    """
    Raised when a commit or push would land on the default branch, which only pull
    requests may change.
    """

    branch: str
    """
    The default branch.
    """

    def error_message(self) -> str:
        return f"{self.branch} is the default branch; work reaches it only through pull requests"

    def suggest_correction(self) -> str:
        return "Start a work branch and commit there."


@dataclass
class AssistantCreditError(DataclassException, ValueError):
    """
    Raised when a commit would credit an assistant as its author or co-author.
    """

    credit: str
    """
    The author or trailer line that credits it.
    """

    def error_message(self) -> str:
        return f"a commit may not credit an assistant: {self.credit}"

    def suggest_correction(self) -> str:
        return "Author the commit as the person running the tool, without the trailer."


@dataclass
class PushRefusedError(DataclassException, RuntimeError):
    """
    Raised when the remote refuses a push, which is never forced.
    """

    branch: str
    """
    The branch that was pushed.
    """

    detail: str
    """
    What git said.
    """

    def error_message(self) -> str:
        return f"pushing {self.branch} was refused: {self.detail}"

    def suggest_correction(self) -> str:
        return "Sync the branch first; a push never overwrites what GitHub holds."


@dataclass
class BranchNotPushedError(DataclassException, RuntimeError):
    """
    Raised when a pull request is asked for a branch GitHub does not have.
    """

    branch: str
    """
    The branch.
    """

    def error_message(self) -> str:
        return f"{self.branch} is not on GitHub"

    def suggest_correction(self) -> str:
        return "Push it first."


@dataclass
class UnpushedCommitsError(DataclassException, RuntimeError):
    """
    Raised when a branch and GitHub's copy of it both have commits the other lacks, and
    the local ones were never pushed.
    """

    branch: str
    """
    The branch.
    """

    def error_message(self) -> str:
        return (
            f"{self.branch} has commits GitHub lacks, and GitHub has commits it lacks"
        )

    def suggest_correction(self) -> str:
        return "Ask the person running the tool how to bring the two together."


# %% the runtime


@dataclass
class NotARuntimeError(DataclassException, RuntimeError):
    """
    Raised when the runtime is to be rebuilt from an interpreter running the workflow
    from a checkout.
    """

    location: str
    """
    The interpreter's environment.
    """

    def error_message(self) -> str:
        return f"{self.location} runs the workflow from a checkout, not from main"

    def suggest_correction(self) -> str:
        return (
            "Update the checkout instead, or run update with the runtime's interpreter."
        )


@dataclass
class RuntimeBuildFailedError(DataclassException, RuntimeError):
    """
    Raised when building the new runtime fails; the runtime in use is left as it was.
    """

    step: str
    """
    The step that failed.
    """

    detail: str
    """
    What it said.
    """

    def error_message(self) -> str:
        return f"rebuilding the runtime failed at {self.step}: {self.detail}"

    def suggest_correction(self) -> str:
        return "The runtime in use is unchanged; fix the cause and run update again."


# %% the checkout


@dataclass
class NotACheckoutError(DataclassException, RuntimeError):
    """
    Raised when a command that works on a checkout runs outside one.
    """

    directory: str
    """
    Where it ran.
    """

    def error_message(self) -> str:
        return f"{self.directory} is not inside a git checkout"

    def suggest_correction(self) -> str:
        return "Run the command inside the checkout it is to work on."
