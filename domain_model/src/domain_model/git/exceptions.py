"""
The errors running git ends in.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from domain_model.exceptions import DataclassException, ExternalCallFailed

if TYPE_CHECKING:
    from domain_model.git.remotes import RemoteBranch
    from domain_model.git.revisions import Revision

# %% errors


@dataclass
class GitCommandFailed(ExternalCallFailed):
    """
    Raised when a git command the caller depends on the result of fails.
    """

    arguments: tuple[str, ...] = ()
    """
    The command and its arguments, ``git`` included, as invoked.
    """

    @property
    def call(self) -> str:
        """:return: The git command line, as invoked."""
        return " ".join(self.arguments)


@dataclass
class UnresolvableReferenceError(DataclassException, LookupError):
    """
    Raised when a git reference a decision depends on names no commit in the checkout.
    """

    revision: Revision
    """
    What git could not resolve.
    """

    def error_message(self) -> str:
        return (
            f"git cannot resolve '{self.revision.revision_name}' to a commit in this "
            f"checkout"
        )

    def suggest_correction(self) -> str:
        return (
            "fetch the branch it names from its remote, and check that the branch "
            "still exists there"
        )


@dataclass
class MalformedReferenceUpdateError(DataclassException, ValueError):
    """
    Raised when a line handed to a ``pre-push`` hook does not describe one reference
    update.
    """

    line: str
    """
    The line as git handed it.
    """

    def error_message(self) -> str:
        return (
            f"'{self.line}' is not a reference update, which git writes as a local "
            f"reference, its commit, a remote reference and its commit"
        )

    def suggest_correction(self) -> str:
        return "Hand the hook only the lines git writes to its input."


@dataclass
class StorageBranchPushRefused(DataclassException, RuntimeError):
    """
    Raised when a storage branch refuses a push even after building on its newest tip.
    """

    branch: RemoteBranch
    """
    The storage branch.
    """

    detail: str
    """
    What git said when it refused.
    """

    def error_message(self) -> str:
        return f"pushing {self.branch.name} was refused: {self.detail}"

    def suggest_correction(self) -> str:
        return "Run the write again; if it keeps failing, check access to the remote."


@dataclass
class StorageBranchWriteConflict(DataclassException, RuntimeError):
    """
    Raised when another writer changed a file on a storage branch that a write, built on
    the tip before, would overwrite.
    """

    branch: RemoteBranch
    """
    The storage branch.
    """

    paths: tuple[Path, ...]
    """
    The files both writers changed.
    """

    def error_message(self) -> str:
        changed = ", ".join(str(path) for path in self.paths)
        return f"{changed} on {self.branch.name} changed since this write was built"

    def suggest_correction(self) -> str:
        return "Fetch the branch, read the files again and write them anew."


@dataclass
class UnjudgedSubcommandError(DataclassException, LookupError):
    """
    Raised when a git subcommand said to read in some forms has nothing telling those
    forms apart.
    """

    subcommand: str
    """
    The subcommand.
    """

    def error_message(self) -> str:
        return f"nothing tells apart the forms of git {self.subcommand} that read"

    def suggest_correction(self) -> str:
        return (
            "add a ReadingForms for it, or mark it as never reading in " "GitSubcommand"
        )
