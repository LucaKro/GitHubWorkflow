"""
What git resolves to a commit in one checkout: a commit, a local branch, a
remote-tracking branch; and the hash a record keeps of a commit.
"""

from __future__ import annotations

import tempfile
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from domain_model.class_property import classproperty
from domain_model.environment import GitVariable
from domain_model.git.commands import (
    GitCommandResult,
    GitCommandRunner,
    RevParseOption,
)
from domain_model.git.exceptions import UnresolvableReferenceError
from domain_model.git.subcommands import GitOption, GitSubcommand

# %% a commit's name


class CommitHash(str):
    """
    A commit's hexadecimal name, as git and GitHub write it, kept by a record that runs
    no git.
    """

    @classproperty
    def abbreviation_length(cls) -> int:
        """
        How many of a commit's leading hexadecimal digits name it in a report.
        """
        return 7

    @property
    def abbreviated(self) -> str:
        """:return: The hash, as a report names it."""
        return self[: self.abbreviation_length]


class ReferenceNamespace(StrEnum):
    """
    The prefixes git files references under, by what they name.
    """

    BRANCHES = "refs/heads/"
    """
    A repository's own branches.
    """

    REMOTE_TRACKING_BRANCHES = "refs/remotes/"
    """
    The branches of each remote, as last fetched, under the remote's name.
    """


# %% a branch's name, and where it was


class BranchName(str):
    """
    A branch's name, without the ``refs/heads/`` prefix, kept by a record that runs no
    git.
    """

    @property
    def reference(self) -> str:
        """:return: The branch's full reference, as the repository holding it files it."""
        return f"{ReferenceNamespace.BRANCHES}{self}"


@dataclass(frozen=True)
class BranchTip:
    """
    The commit a branch was at when it was read.
    """

    branch: BranchName
    """
    The branch.
    """

    commit: CommitHash
    """
    The commit it was at.
    """

    def __str__(self) -> str:
        """:return: The branch and its commit, abbreviated."""
        return f"{self.branch} at {self.commit.abbreviated}"


# %% references outside the namespaces


class SpecialReference(StrEnum):
    """
    The references git keeps outside any namespace, for the checkout's own state.
    """

    CHECKED_OUT = "HEAD"
    """
    The commit checked out, through the branch checked out unless it is detached.
    """

    MERGED = "MERGE_HEAD"
    """
    The commit being merged in, set from the start of a merge until it is committed or
    undone.
    """


class TreeEntryMode(StrEnum):
    """
    The modes a tree records its entries with.
    """

    REGULAR_FILE = "100644"
    """
    A file that is not executable.
    """


# %% the options of the subcommands run here


class FetchOption(GitOption):
    """
    The options of ``git fetch``.
    """

    QUIET = "--quiet", True
    """
    Print no progress.
    """

    VERBOSE = "--verbose", True
    """
    Print every reference fetched.
    """

    NO_WRITE_FETCH_HEAD = "--no-write-fetch-head", True
    """
    Leave ``FETCH_HEAD`` alone.
    """

    PRUNE = "--prune", True
    """
    Forget the remote-tracking branches the remote no longer has.
    """

    ALL = "--all", True
    """
    Fetch from every remote.
    """

    TAGS = "--tags", True
    """
    Fetch every tag too.
    """

    NO_TAGS = "--no-tags", True
    """
    Fetch no tag.
    """

    DEPTH = "--depth", True
    """
    Fetch only the given number of commits of each history.
    """

    UNSHALLOW = "--unshallow", True
    """
    Fetch the whole history of a shallow clone.
    """

    DRY_RUN = "--dry-run", True
    """
    Show what would be fetched, storing nothing.
    """

    FORCE = "--force", True
    """
    Let a fetched reference move to a commit that does not descend from its own.
    """

    SET_UPSTREAM = "--set-upstream", False
    """
    Configure the checked-out branch to track what is fetched.
    """

    REFERENCE_MAP = "--refmap", False
    """
    Store what is fetched where the given refspec says, a local branch among them.
    """

    UPDATE_HEAD_OK = "--update-head-ok", False
    """
    Let the fetch move the checked-out branch.
    """


class MergeBaseOption(GitOption):
    """
    The options of ``git merge-base``.
    """

    IS_ANCESTOR = "--is-ancestor", True
    """
    Succeed only when the first commit is in the second's history.
    """


class RevListOption(GitOption):
    """
    The options of ``git rev-list``.
    """

    COUNT = "--count", True
    """
    Print how many commits it lists instead of listing them.
    """


class MergeTreeOption(GitOption):
    """
    The options of ``git merge-tree``.
    """

    WRITE_TREE = "--write-tree", True
    """
    Merge in full, storing the merged tree as an object nothing refers to.
    """


class HashObjectOption(GitOption):
    """
    The options of ``git hash-object``.
    """

    WRITE = "-w", False
    """
    Store the content as an object.
    """


class UpdateIndexOption(GitOption):
    """
    The options of ``git update-index``.
    """

    ADD = "--add", False
    """
    Let a file not yet in the index be added.
    """

    CACHE_INFORMATION = "--cacheinfo", False
    """
    Set one entry from a mode, an object and a path.
    """


class CommitTreeOption(GitOption):
    """
    The options of ``git commit-tree``.
    """

    PARENT = "-p", True
    """
    Name a parent of the commit.
    """

    MESSAGE = "-m", True
    """
    Give the commit message.
    """


class CheckoutIndexOption(GitOption):
    """
    The options of ``git checkout-index``.
    """

    ALL = "--all", True
    """
    Write every file of the index.
    """

    PREFIX = "--prefix", True
    """
    Write the files under the given prefix.
    """


class SwitchOption(GitOption):
    """
    The options of ``git switch``.
    """

    QUIET = "--quiet", True
    """
    Print no feedback.
    """

    NO_TRACK = "--no-track", True
    """
    Make the new branch track no other.
    """

    CREATE = "--create", False
    """
    Create the branch switched to.
    """


# %% anything that resolves to a commit


class Revision(ABC):
    """
    Something git resolves to a commit in one checkout.
    """

    git: GitCommandRunner
    """
    Runs git in the checkout it is resolved in.
    """

    @property
    @abstractmethod
    def revision_name(self) -> str:
        """:return: How git names it on a command line."""

    def commit_or_none(self) -> Commit | None:
        """:return: The commit it is at, ``None`` when git cannot resolve it."""
        resolved = self.git.attempt(
            GitSubcommand.REV_PARSE,
            RevParseOption.VERIFY,
            RevParseOption.QUIET,
            f"{self.revision_name}^{{commit}}",
        )
        return (
            Commit(self.git, CommitHash(resolved.output))
            if resolved.succeeded
            else None
        )

    def commit(self) -> Commit:
        """
        :return: The commit it is at.
        :raises UnresolvableReferenceError: If git cannot resolve it.
        """
        commit = self.commit_or_none()
        if commit is None:
            raise UnresolvableReferenceError(self)
        return commit

    def is_contained_in(self, other: Revision) -> bool:
        """
        :param other: Another revision.
        :return: Whether this one is in *other*'s history, itself included.
        """
        return self.git.attempt(
            GitSubcommand.MERGE_BASE,
            MergeBaseOption.IS_ANCESTOR,
            self.revision_name,
            other.revision_name,
        ).succeeded

    def commits_ahead(self, base: Revision) -> int:
        """
        :param base: Another revision.
        :return: How many commits this one holds that *base* lacks.
        """
        return int(
            self.git.run(
                GitSubcommand.REV_LIST,
                RevListOption.COUNT,
                f"{base.revision_name}..{self.revision_name}",
            )
        )

    def conflicts_when_merged(self, other: Revision) -> bool:
        """
        :param other: Another revision.
        :return: Whether merging the two conflicts; no branch and no file is touched.
        """
        return not self.git.attempt(
            GitSubcommand.MERGE_TREE,
            MergeTreeOption.WRITE_TREE,
            self.revision_name,
            other.revision_name,
        ).succeeded

    def file_text(self, path: Path) -> str | None:
        """
        :param path: A file, relative to the repository's root.
        :return: Its text as this revision records it, ``None`` when it has no such
            file.
        """
        shown = self.git.attempt(GitSubcommand.SHOW, f"{self.revision_name}:{path}")
        return shown.standard_output if shown.succeeded else None

    def file_blob(self, path: Path) -> str | None:
        """
        :param path: A file, relative to the repository's root.
        :return: The object holding its content in this revision, ``None`` when it has
            no such file.
        """
        found = self.git.attempt(
            GitSubcommand.REV_PARSE,
            RevParseOption.VERIFY,
            RevParseOption.QUIET,
            f"{self.revision_name}:{path}",
        )
        return found.output if found.succeeded else None


# %% files a commit records


@dataclass(frozen=True)
class TextFiles:
    """
    Text files to commit, by their paths relative to the repository's root.
    """

    texts: Mapping[Path, str]
    """
    The text of each file, by its path.
    """

    @property
    def paths(self) -> list[Path]:
        """:return: Every file's path, in the order given."""
        return list(self.texts)

    def combined(self, other: TextFiles) -> TextFiles:
        """
        :param other: More files.
        :return: These files and *other*'s, *other*'s text winning for a path both
            hold.
        """
        return TextFiles({**self.texts, **other.texts})


# %% a commit


@dataclass(frozen=True)
class Commit(Revision):
    """
    One commit in a checkout.
    """

    git: GitCommandRunner
    """
    Runs git in the checkout the commit is in.
    """

    hash: CommitHash
    """
    The commit's name.
    """

    @property
    def revision_name(self) -> str:
        return self.hash

    def write_child(self, files: TextFiles, message: str) -> Commit:
        """
        Write a new commit on this one into the repository, holding this commit's files
        and *files* over them, without checking anything out.

        :param files: The text of each file to write.
        :param message: The commit message.
        :return: The new commit.
        """
        return self._write(self.git, files, message, self)

    @classmethod
    def write_root(
        cls, git: GitCommandRunner, files: TextFiles, message: str
    ) -> Commit:
        """
        Write a new commit with no parent into the repository, holding *files* alone,
        without checking anything out.

        :param git: Runs git in the checkout the commit is written in.
        :param files: The text of each file to write.
        :param message: The commit message.
        :return: The new commit.
        """
        return cls._write(git, files, message, None)

    @classmethod
    def _write(
        cls,
        git: GitCommandRunner,
        files: TextFiles,
        message: str,
        parent: Commit | None,
    ) -> Commit:
        """
        Write a commit object from files, in an index of the commit's own.

        :param git: Runs git in the checkout the commit is written in.
        :param files: The text of each file to write, over the parent's files.
        :param message: The commit message.
        :param parent: The commit to build on, ``None`` for a commit with no parent.
        :return: The new commit.
        """
        with tempfile.TemporaryDirectory() as directory:
            index = {GitVariable.INDEX_FILE: str(Path(directory) / "index")}
            if parent is not None:
                git.run(GitSubcommand.READ_TREE, parent.hash, environment=index)
            for path, text in files.texts.items():
                staged = Path(directory) / "content"
                staged.write_text(text)
                blob = git.run(
                    GitSubcommand.HASH_OBJECT, HashObjectOption.WRITE, str(staged)
                )
                git.run(
                    GitSubcommand.UPDATE_INDEX,
                    UpdateIndexOption.ADD,
                    UpdateIndexOption.CACHE_INFORMATION,
                    f"{TreeEntryMode.REGULAR_FILE},{blob},{path}",
                    environment=index,
                )
            tree = git.run(GitSubcommand.WRITE_TREE, environment=index)
        parents = () if parent is None else (CommitTreeOption.PARENT, parent.hash)
        created = git.run(
            GitSubcommand.COMMIT_TREE, tree, *parents, CommitTreeOption.MESSAGE, message
        )
        return cls(git, CommitHash(created))

    def export_files(self, destination: Path) -> None:
        """
        Write the files the commit records into a directory, leaving the checkout, its
        index and ``HEAD`` alone.

        :param destination: The directory, created when absent.
        """
        destination.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as directory:
            index = {GitVariable.INDEX_FILE: str(Path(directory) / "index")}
            self.git.run(GitSubcommand.READ_TREE, self.hash, environment=index)
            self.git.run(
                GitSubcommand.CHECKOUT_INDEX,
                CheckoutIndexOption.ALL,
                f"{CheckoutIndexOption.PREFIX}={destination.resolve()}/",
                environment=index,
            )


# %% a local branch


@dataclass(frozen=True)
class LocalBranch(Revision):
    """
    One branch of the checkout's own.
    """

    git: GitCommandRunner
    """
    Runs git in the checkout the branch is in.
    """

    name: BranchName
    """
    The branch's name.
    """

    @property
    def revision_name(self) -> str:
        return self.name.reference

    def create(self, start: Revision) -> None:
        """
        Create the branch and check it out, tracking no branch: not even a remote's it
        starts at.

        :param start: What it starts at.
        :raises GitCommandFailed: If the branch exists already.
        """
        self.git.run(
            GitSubcommand.SWITCH,
            SwitchOption.QUIET,
            SwitchOption.NO_TRACK,
            SwitchOption.CREATE,
            self.name,
            start.revision_name,
        )

    def switch(self) -> None:
        """
        Check the branch out, creating it to track the remote's when only a remote has
        it.

        :raises GitCommandFailed: If no branch of that name exists, or uncommitted changes
            would be overwritten.
        """
        self.git.run(GitSubcommand.SWITCH, SwitchOption.QUIET, self.name)

    def fast_forward(self, target: Revision) -> GitCommandResult:
        """
        Move the branch, while it is not checked out, forward to a revision.

        :param target: Where to move it, a descendant of its commit.
        :return: The finished move, refused when the branch has commits *target* lacks
            or is checked out in any worktree.
        """
        return self.git.attempt(
            GitSubcommand.FETCH,
            FetchOption.QUIET,
            ".",
            f"{target.revision_name}:{self.revision_name}",
        )
