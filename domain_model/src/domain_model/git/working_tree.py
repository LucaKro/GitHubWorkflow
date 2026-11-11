"""
A checkout's working tree: the branch checked out, the changes made in it, and a merge
in progress.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from domain_model.git.commands import GitCommandResult, GitCommandRunner
from domain_model.git.revisions import Commit, CommitHash, LocalBranch, Revision
from domain_model.locations import GitStateFile

# %% the working tree


@dataclass(frozen=True)
class WorkingTree:
    """
    The files checked out in one checkout, and the branch they are on.
    """

    git: GitCommandRunner
    """
    Runs git in the checkout.
    """

    def checked_out_branch(self) -> LocalBranch | None:
        """:return: The branch a commit or a push would move, ``None`` on a detached
        ``HEAD``."""
        name = self.git.run("branch", "--show-current")
        return LocalBranch(self.git, name) if name else None

    def head(self) -> Commit:
        """:return: The commit checked out."""
        return Commit(self.git, CommitHash(self.git.run("rev-parse", "HEAD")))

    def stage(self, paths: Sequence[Path]) -> None:
        """
        Stage the current content of some paths for the next commit.

        :param paths: The files and directories to stage, as they are in the working
            tree; one no longer there is staged as removed.
        """
        present = [
            str(path) for path in paths if (self.git.working_directory / path).exists()
        ]
        removed = [str(path) for path in paths if str(path) not in present]
        if present:
            self.git.run("add", "--", *present)
        if removed:
            self.git.run(
                "rm", "-r", "--quiet", "--cached", "--ignore-unmatch", "--", *removed
            )

    def commit_staged(self, message: str) -> Commit:
        """
        Commit what is staged, a merge in progress included.

        :param message: The commit message.
        :return: The new commit.
        :raises GitCommandFailed: If nothing is staged.
        """
        self.git.run("commit", "--quiet", "--message", message)
        return self.head()

    def commit(self, message: str, paths: Sequence[Path]) -> Commit:
        """
        Commit the current content of some paths.

        :param message: The commit message.
        :param paths: The files and directories to commit, as they are in the working
            tree; one no longer there is committed as removed.
        :return: The new commit.
        :raises GitCommandFailed: If nothing changed.
        """
        self.stage(paths)
        return self.commit_staged(message)

    def has_uncommitted_changes(self) -> bool:
        """
        :return: Whether a tracked file is changed in the working tree or the index;
            untracked files do not count.
        """
        return bool(self.git.run("status", "--porcelain", "--untracked-files=no"))

    def fast_forward(self, target: Revision) -> GitCommandResult:
        """
        :param target: What to move the checked-out branch to.
        :return: The finished move, failed when the branch has commits *target* lacks.
        """
        return self.git.attempt("merge", "--quiet", "--ff-only", target.revision_name)

    def reset_kept(self, target: Revision) -> None:
        """
        Move the checked-out branch to another commit, keeping uncommitted changes.

        :param target: The commit to move it to.
        :raises GitCommandFailed: If an uncommitted change would be lost.
        """
        self.git.run("reset", "--quiet", "--keep", target.revision_name)


# %% a merge


class MergeReference(StrEnum):
    """
    The references git sets while a merge is in progress.
    """

    MERGED = "MERGE_HEAD"
    """
    The commit being merged in, set from the start of a merge until it is committed or
    undone.
    """


@dataclass(frozen=True)
class Merge:
    """
    A merge into the branch a working tree has checked out, from its start until it is
    committed or undone.
    """

    tree: WorkingTree
    """
    The working tree merged into.
    """

    def start(self, merged: Revision, message: str) -> GitCommandResult:
        """
        Merge a revision into the checked-out branch, committing the merge with the
        message given, or fast-forwarding when the branch has no commits of its own.

        :param merged: What to merge.
        :param message: The merge commit's message.
        :return: The finished merge, whose failure is a conflict only when it left
            files conflicting; :meth:`conflicted_files` names them then.
        """
        return self.tree.git.attempt(
            "merge", "--no-edit", "--message", message, merged.revision_name
        )

    def in_progress(self) -> bool:
        """:return: Whether a merge was started and neither committed nor undone yet."""
        return self.tree.git.attempt(
            "rev-parse", "--verify", "--quiet", MergeReference.MERGED
        ).succeeded

    def message(self) -> str:
        """
        :return: The commit message the merge in progress was started with, without the
            lines git adds as comments.
        """
        written = self.tree.git.git_path(GitStateFile.MERGE_MESSAGE).read_text()
        lines = written.splitlines()
        return "\n".join(line for line in lines if not line.startswith("#")).strip()

    def conflicted_files(self) -> list[str]:
        """:return: The files the merge in progress left conflicting."""
        return self.tree.git.run("diff", "--name-only", "--diff-filter=U").splitlines()

    def abort(self) -> None:
        """
        Undo the merge in progress, back to the commit and files before it.
        """
        self.tree.git.run("merge", "--abort")
