"""
A checkout's working tree: the branch checked out, the changes made in it, and a merge
in progress.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from domain_model.git.commands import (
    GitCommandResult,
    GitCommandRunner,
    RevParseOption,
)
from domain_model.git.revisions import (
    BranchName,
    Commit,
    CommitHash,
    LocalBranch,
    Revision,
    SpecialReference,
)
from domain_model.git.subcommands import GitOption, GitSubcommand
from domain_model.locations import GitStateFile

# %% the options of the subcommands run here


class BranchOption(GitOption):
    """
    The options of ``git branch``.
    """

    LIST = "--list", True
    """
    List the branches, those matching the patterns given when any is.
    """

    LIST_SHORT = "-l", True
    """
    List the branches, short form.
    """

    ALL = "--all", True
    """
    List the remote-tracking branches with the local ones.
    """

    ALL_SHORT = "-a", True
    """
    List the remote-tracking branches with the local ones, short form.
    """

    REMOTES = "--remotes", True
    """
    List the remote-tracking branches alone.
    """

    REMOTES_SHORT = "-r", True
    """
    List the remote-tracking branches alone, short form.
    """

    VERBOSE = "--verbose", True
    """
    List each branch with its commit.
    """

    VERBOSE_SHORT = "-v", True
    """
    List each branch with its commit, short form.
    """

    VERY_VERBOSE = "-vv", True
    """
    List each branch with its commit and the branch it tracks.
    """

    SHOW_CURRENT = "--show-current", True
    """
    Print the checked-out branch, nothing on a detached ``HEAD``.
    """

    COLOR = "--color", True
    """
    Colour the list.
    """

    NO_COLOR = "--no-color", True
    """
    Leave the list uncoloured.
    """

    CONTAINS = "--contains", True
    """
    List only the branches whose history holds the given commit.
    """

    NO_CONTAINS = "--no-contains", True
    """
    List only the branches whose history lacks the given commit.
    """

    MERGED = "--merged", True
    """
    List only the branches the given commit's history holds.
    """

    NO_MERGED = "--no-merged", True
    """
    List only the branches the given commit's history lacks.
    """

    POINTS_AT = "--points-at", True
    """
    List only the branches at the given commit.
    """

    SORT = "--sort", True
    """
    Order the list by the given key.
    """

    FORMAT = "--format", True
    """
    Print each branch as the given format says.
    """


class RmOption(GitOption):
    """
    The options of ``git rm``.
    """

    RECURSIVE = "-r", True
    """
    Remove a directory's files.
    """

    QUIET = "--quiet", True
    """
    Print nothing.
    """

    CACHED = "--cached", True
    """
    Remove from the index only, keeping the working files.
    """

    IGNORE_UNMATCH = "--ignore-unmatch", True
    """
    Succeed even when a path matches no file.
    """


class CommitOption(GitOption):
    """
    The options of ``git commit``.
    """

    QUIET = "--quiet", True
    """
    Print nothing.
    """

    MESSAGE = "--message", True
    """
    Give the commit message.
    """


class StatusOption(GitOption):
    """
    The options of ``git status``.
    """

    PORCELAIN = "--porcelain", True
    """
    Print each changed file on a line, in a form meant for programs.
    """

    TRACKED_ONLY = "--untracked-files=no", True
    """
    Leave untracked files out.
    """


class MergeOption(GitOption):
    """
    The options of ``git merge``.
    """

    QUIET = "--quiet", True
    """
    Print nothing.
    """

    FAST_FORWARD_ONLY = "--ff-only", True
    """
    Only move the branch forward, failing when it has commits of its own.
    """

    NO_EDIT = "--no-edit", True
    """
    Commit with the message given, without opening an editor.
    """

    MESSAGE = "--message", True
    """
    Give the merge commit's message.
    """

    ABORT = "--abort", False
    """
    Undo the merge in progress.
    """


class ResetOption(GitOption):
    """
    The options of ``git reset``.
    """

    QUIET = "--quiet", True
    """
    Print nothing.
    """

    KEEP = "--keep", True
    """
    Keep uncommitted changes, failing when one would be lost.
    """


class DiffOption(GitOption):
    """
    The options of ``git diff``.
    """

    NAME_ONLY = "--name-only", True
    """
    Print only the changed files' names.
    """

    CONFLICTED_ONLY = "--diff-filter=U", True
    """
    Show only the files left conflicting.
    """


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
        name = self.git.run(GitSubcommand.BRANCH, BranchOption.SHOW_CURRENT)
        return LocalBranch(self.git, BranchName(name)) if name else None

    def head(self) -> Commit:
        """:return: The commit checked out."""
        checked_out = self.git.run(
            GitSubcommand.REV_PARSE, SpecialReference.CHECKED_OUT
        )
        return Commit(self.git, CommitHash(checked_out))

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
            self.git.run(GitSubcommand.ADD, GitOption.end_of_options, *present)
        if removed:
            self.git.run(
                GitSubcommand.RM,
                RmOption.RECURSIVE,
                RmOption.QUIET,
                RmOption.CACHED,
                RmOption.IGNORE_UNMATCH,
                GitOption.end_of_options,
                *removed,
            )

    def commit_staged(self, message: str) -> Commit:
        """
        Commit what is staged, a merge in progress included.

        :param message: The commit message.
        :return: The new commit.
        :raises GitCommandFailed: If nothing is staged.
        """
        self.git.run(
            GitSubcommand.COMMIT, CommitOption.QUIET, CommitOption.MESSAGE, message
        )
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
        return bool(
            self.git.run(
                GitSubcommand.STATUS, StatusOption.PORCELAIN, StatusOption.TRACKED_ONLY
            )
        )

    def fast_forward(self, target: Revision) -> GitCommandResult:
        """
        :param target: What to move the checked-out branch to.
        :return: The finished move, failed when the branch has commits *target* lacks.
        """
        return self.git.attempt(
            GitSubcommand.MERGE,
            MergeOption.QUIET,
            MergeOption.FAST_FORWARD_ONLY,
            target.revision_name,
        )

    def reset_kept(self, target: Revision) -> None:
        """
        Move the checked-out branch to another commit, keeping uncommitted changes.

        :param target: The commit to move it to.
        :raises GitCommandFailed: If an uncommitted change would be lost.
        """
        self.git.run(
            GitSubcommand.RESET,
            ResetOption.QUIET,
            ResetOption.KEEP,
            target.revision_name,
        )


# %% a merge


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
            GitSubcommand.MERGE,
            MergeOption.NO_EDIT,
            MergeOption.MESSAGE,
            message,
            merged.revision_name,
        )

    def in_progress(self) -> bool:
        """:return: Whether a merge was started and neither committed nor undone yet."""
        return self.tree.git.attempt(
            GitSubcommand.REV_PARSE,
            RevParseOption.VERIFY,
            RevParseOption.QUIET,
            SpecialReference.MERGED,
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
        conflicted = self.tree.git.run(
            GitSubcommand.DIFF, DiffOption.NAME_ONLY, DiffOption.CONFLICTED_ONLY
        )
        return conflicted.splitlines()

    def abort(self) -> None:
        """
        Undo the merge in progress, back to the commit and files before it.
        """
        self.tree.git.run(GitSubcommand.MERGE, MergeOption.ABORT)
