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
from domain_model.git.commands import GitCommandResult, GitCommandRunner
from domain_model.git.exceptions import UnresolvableReferenceError

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
            "rev-parse", "--verify", "--quiet", f"{self.revision_name}^{{commit}}"
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
            raise UnresolvableReferenceError(self.revision_name)
        return commit

    def is_contained_in(self, other: Revision) -> bool:
        """
        :param other: Another revision.
        :return: Whether this one is in *other*'s history, itself included.
        """
        return self.git.attempt(
            "merge-base", "--is-ancestor", self.revision_name, other.revision_name
        ).succeeded

    def commits_ahead(self, base: Revision) -> int:
        """
        :param base: Another revision.
        :return: How many commits this one holds that *base* lacks.
        """
        return int(
            self.git.run(
                "rev-list", "--count", f"{base.revision_name}..{self.revision_name}"
            )
        )

    def conflicts_when_merged(self, other: Revision) -> bool:
        """
        :param other: Another revision.
        :return: Whether merging the two conflicts; no branch and no file is touched.
        """
        return not self.git.attempt(
            "merge-tree", "--write-tree", self.revision_name, other.revision_name
        ).succeeded

    def file_text(self, path: Path) -> str | None:
        """
        :param path: A file, relative to the repository's root.
        :return: Its text as this revision records it, ``None`` when it has no such
            file.
        """
        shown = self.git.attempt("show", f"{self.revision_name}:{path}")
        return shown.standard_output if shown.succeeded else None

    def file_blob(self, path: Path) -> str | None:
        """
        :param path: A file, relative to the repository's root.
        :return: The object holding its content in this revision, ``None`` when it has
            no such file.
        """
        found = self.git.attempt(
            "rev-parse", "--verify", "--quiet", f"{self.revision_name}:{path}"
        )
        return found.output if found.succeeded else None


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

    @classmethod
    def create(
        cls,
        git: GitCommandRunner,
        files: Mapping[Path, str],
        message: str,
        parent: Commit | None = None,
    ) -> Commit:
        """
        Commit files without checking anything out, in an index of the commit's own.

        :param git: Runs git in the checkout the commit is made in.
        :param files: The text of each file to write, over the parent's files.
        :param message: The commit message.
        :param parent: The commit to build on, ``None`` for a commit with no parent.
        :return: The new commit.
        """
        with tempfile.TemporaryDirectory() as directory:
            index = {GitVariable.INDEX_FILE: str(Path(directory) / "index")}
            if parent is not None:
                git.run("read-tree", parent.hash, environment=index)
            for path, text in files.items():
                staged = Path(directory) / "content"
                staged.write_text(text)
                blob = git.run("hash-object", "-w", str(staged))
                git.run(
                    "update-index",
                    "--add",
                    "--cacheinfo",
                    f"100644,{blob},{path}",
                    environment=index,
                )
            tree = git.run("write-tree", environment=index)
        parents = () if parent is None else ("-p", parent.hash)
        return cls(
            git, CommitHash(git.run("commit-tree", tree, *parents, "-m", message))
        )

    def export_files(self, destination: Path) -> None:
        """
        Write the files the commit records into a directory, leaving the checkout, its
        index and ``HEAD`` alone.

        :param destination: The directory, created when absent.
        """
        destination.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as directory:
            index = {GitVariable.INDEX_FILE: str(Path(directory) / "index")}
            self.git.run("read-tree", self.hash, environment=index)
            self.git.run(
                "checkout-index",
                "--all",
                f"--prefix={destination.resolve()}/",
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

    name: str
    """
    The branch's name.
    """

    @property
    def revision_name(self) -> str:
        return f"{ReferenceNamespace.BRANCHES}{self.name}"

    def create(self, start: Revision) -> None:
        """
        Create the branch and check it out, tracking no branch: not even a remote's it
        starts at.

        :param start: What it starts at.
        :raises GitCommandFailed: If the branch exists already.
        """
        self.git.run(
            "switch",
            "--quiet",
            "--no-track",
            "--create",
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
        self.git.run("switch", "--quiet", self.name)

    def fast_forward(self, target: Revision) -> GitCommandResult:
        """
        Move the branch, while it is not checked out, forward to a revision.

        :param target: Where to move it, a descendant of its commit.
        :return: The finished move, refused when the branch has commits *target* lacks
            or is checked out in any worktree.
        """
        return self.git.attempt(
            "fetch", "--quiet", ".", f"{target.revision_name}:{self.revision_name}"
        )
