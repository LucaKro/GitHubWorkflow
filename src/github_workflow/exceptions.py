"""
The errors the workflow's commands end in.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from basstler_domain_model.exceptions import DataclassException

if TYPE_CHECKING:
    from basstler_domain_model.repository import Repository

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


@dataclass
class ForeignRepositoryCloneError(DataclassException, PermissionError):
    """
    Raised when a clone is asked for of a repository the owner does not own.
    """

    repository: Repository
    """
    The repository asked for.
    """

    owner: str
    """
    The account whose repositories alone are cloned.
    """

    def error_message(self) -> str:
        return f"{self.repository} belongs to {self.repository.owner}, not {self.owner}"

    def suggest_correction(self) -> str:
        return f"Fork it to {self.owner}'s account and clone the fork."


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


@dataclass
class BranchDeletedFromGitHubError(DataclassException, LookupError):
    """
    Raised when a branch that was on GitHub is no longer there, as after its pull
    request was merged.
    """

    branch: str
    """
    The branch.
    """

    def error_message(self) -> str:
        return f"{self.branch} was on GitHub and has been deleted there"

    def suggest_correction(self) -> str:
        return (
            "Do not push it again; ask the person running the tool whether its work "
            "is finished."
        )


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


# %% pull requests


@dataclass
class NotADraftError(DataclassException, RuntimeError):
    """
    Raised when a pull request to be rewritten is ready for review or closed.
    """

    number: int
    """
    The pull request.
    """

    def error_message(self) -> str:
        return f"#{self.number} is not an open draft"

    def suggest_correction(self) -> str:
        return "Changing it needs the go-ahead of the person running the tool."


# %% discarding branches


@dataclass
class UndiscardableBranchError(DataclassException, ValueError):
    """
    Raised when the branch to discard is the default branch or the notes branch, which
    are never deleted.
    """

    branch: str
    """
    The branch.
    """

    def error_message(self) -> str:
        return f"{self.branch} is never deleted, so it cannot be discarded"

    def suggest_correction(self) -> str:
        return "Name the work branch to discard."


@dataclass
class NothingToDiscardError(DataclassException, LookupError):
    """
    Raised when the branch to discard is not on GitHub, so there is nothing to delete.
    """

    branch: str
    """
    The branch.
    """

    def error_message(self) -> str:
        return f"{self.branch} is not on GitHub, so there is nothing to delete"

    def suggest_correction(self) -> str:
        return "Only a branch on GitHub is discarded; leave this one as it is."


# %% findings


@dataclass
class NotAFindingError(DataclassException, LookupError):
    """
    Raised when a finding to be accepted, shelved or rejected is none, or not in a stage
    that allows it.
    """

    number: int
    """
    The issue asked for.
    """

    def error_message(self) -> str:
        return f"#{self.number} is not an open finding that can be decided this way"

    def suggest_correction(self) -> str:
        return "List the findings to see the stage each one is in."
