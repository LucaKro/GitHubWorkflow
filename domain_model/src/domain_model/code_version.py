"""
Which version of the domain model is running, and the commit it was built from, as far
as the installation tells.
"""

from __future__ import annotations

import importlib.metadata
import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from urllib.request import url2pathname

from domain_model.class_property import classproperty
from domain_model.git.commands import GitCommandRunner
from domain_model.git.options import RevParseOption
from domain_model.git.references import SpecialReference
from domain_model.git.revisions import CommitHash
from domain_model.git.subcommands import GitSubcommand

# %% where the installation came from


class DirectUrlKey(StrEnum):
    """
    The keys of the ``direct_url.json`` an installer writes beside a distribution it
    installed from a URL or a directory.
    """

    URL = "url"
    """
    Where the distribution was installed from.
    """

    VCS_INFO = "vcs_info"
    """
    The version control state it was installed at, present for a repository.
    """

    COMMIT_ID = "commit_id"
    """
    The commit it was installed at.
    """


@dataclass(frozen=True)
class DirectUrl:
    """
    Where an installed distribution came from, as its ``direct_url.json`` says.
    """

    url: str
    """
    Where it was installed from.
    """

    commit: CommitHash | None
    """
    The commit it was installed at, ``None`` when it was not installed from a
    repository.
    """

    @classproperty
    def file_name(cls) -> str:
        """
        The file the installer writes beside the distribution's metadata.
        """
        return "direct_url.json"

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> DirectUrl:
        """
        :param data: The file's content.
        :return: Where the distribution came from.
        """
        vcs_info = data.get(DirectUrlKey.VCS_INFO, {})
        commit = vcs_info.get(DirectUrlKey.COMMIT_ID)
        return cls(
            data[DirectUrlKey.URL], None if commit is None else CommitHash(commit)
        )

    @property
    def directory(self) -> Path | None:
        """:return: The local directory it was installed from, ``None`` for a remote
        URL."""
        parts = urlsplit(self.url)
        return Path(url2pathname(parts.path)) if parts.scheme == "file" else None


# %% the running version


class CodeVersionKey(StrEnum):
    """
    The keys of a :class:`CodeVersion` as JSON.
    """

    VERSION = "version"
    """
    The distribution's version.
    """

    COMMIT = "commit"
    """
    The commit it was built from.
    """


@dataclass(frozen=True)
class CodeVersion:
    """
    The version of the domain model, and the commit it was built from.
    """

    version: str | None
    """
    The installed distribution's version, ``None`` when it is not installed.
    """

    commit: CommitHash | None
    """
    The commit it was built from, ``None`` when the installation cannot tell.
    """

    @classproperty
    def distribution_name(cls) -> str:
        """
        The name the domain model is installed under.
        """
        return "domain-model"

    @classmethod
    def running(cls) -> CodeVersion:
        """
        :return: The version running now; what it cannot tell is ``None``, never
            guessed.
        """
        found = importlib.metadata.distributions(name=cls.distribution_name)
        distribution = next(iter(found), None)
        if distribution is None:
            return cls(None, cls.checkout_commit(Path(__file__).parent))
        recorded = distribution.read_text(DirectUrl.file_name)
        source = None if recorded is None else DirectUrl.from_json(json.loads(recorded))
        if source is not None and source.commit is not None:
            return cls(distribution.version, source.commit)
        directories = [Path(__file__).parent]
        if source is not None and source.directory is not None:
            directories.insert(0, source.directory)
        commits = (cls.checkout_commit(directory) for directory in directories)
        return cls(
            distribution.version,
            next((commit for commit in commits if commit is not None), None),
        )

    @staticmethod
    def checkout_commit(directory: Path) -> CommitHash | None:
        """
        :param directory: A directory.
        :return: The commit checked out in the git checkout it is inside, ``None`` when
            it is inside none or git cannot tell.
        """
        git = GitCommandRunner.enclosing(directory)
        if git is None:
            return None
        resolved = git.attempt(
            GitSubcommand.REV_PARSE,
            RevParseOption.VERIFY,
            RevParseOption.QUIET,
            SpecialReference.CHECKED_OUT,
        )
        return CommitHash(resolved.output) if resolved.succeeded else None

    def to_json(self) -> dict[str, str | None]:
        """:return: The version, as :meth:`from_json` reads it."""
        return {
            CodeVersionKey.VERSION: self.version,
            CodeVersionKey.COMMIT: self.commit,
        }

    @classmethod
    def from_json(cls, data: dict[str, str | None]) -> CodeVersion:
        """
        :param data: A version, as :meth:`to_json` writes it.
        :return: The version.
        """
        commit = data[CodeVersionKey.COMMIT]
        return cls(
            data[CodeVersionKey.VERSION], None if commit is None else CommitHash(commit)
        )

    @property
    def described(self) -> str:
        """:return: The version and the commit, as a message names them."""
        version = self.version or "an uninstalled version"
        commit = "commit unknown" if self.commit is None else self.commit.abbreviated
        return f"{self.distribution_name} {version} ({commit})"
