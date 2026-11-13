"""
Every file and directory this package names, each written once.
"""

from __future__ import annotations

import os
from enum import ReprEnum
from pathlib import Path

# %% the enumeration every set of paths extends


class PathEnumeration(Path, ReprEnum):
    """
    An enumeration whose members are paths.

    A member is the path it names - joined onto another with ``/``, opened, passed to a
    subprocess, formatted as its text - and every path derived from one is a plain
    :class:`~pathlib.Path`.

    .. warning:: ``Path.name`` shadows the enumeration's own ``name``: ``member.name`` is
        the path's last component, and the member's name is ``member._name_``.
    """

    def __hash__(self) -> int:
        """
        Hash as the path does, so a member and its path are one key; the enumeration's
        own hash would tell them apart.
        """
        return hash(self.value)

    def __eq__(self, value: object, /) -> bool:
        """
        The value of the Enum should be equal to an equivalent Path instance.

        :param value: A Path instance to compare.
        :return: True if the value is equal to an equivalent Path instance, False
            otherwise.
        """
        return self.value == value

    def with_segments(self, *path_segments: str | os.PathLike[str]) -> Path:
        """
        :param path_segments: The segments of a path derived from this one.
        :return: That path, as a plain path rather than a lookup of a member by value.
        """
        return Path(*path_segments)


# %% the package's own files


class PackageLocation(PathEnumeration):
    """
    The package's own directory and the files shipped in it, as absolute paths.
    """

    DIRECTORY = Path(__file__).parent
    """
    The package's own directory.
    """

    QUERIES = DIRECTORY / "github" / "queries"
    """
    The GraphQL documents the readers send.
    """

    README = DIRECTORY.parent.parent / "README.md"
    """
    The domain model's README, there only when the package runs from its source.
    """


# %% git's state


class GitStateFile(PathEnumeration):
    """
    The files git keeps in a repository's git directory, relative to it.
    """

    MERGE_MESSAGE = Path("MERGE_MSG")
    """
    The commit message a merge in progress was started with.
    """

    FETCH_HEAD = Path("FETCH_HEAD")
    """
    What the last fetch brought in, rewritten by every fetch.
    """

    EXCLUDE = Path("info/exclude")
    """
    The repository's own ignore list, which is never committed.
    """

    PRE_PUSH_HOOK = Path("hooks/pre-push")
    """
    The hook git runs before every push, which may refuse it.
    """


# %% what GitHub reads in a repository


class GitHubRepositoryFile(PathEnumeration):
    """
    The places in a repository GitHub reads, relative to its root.
    """

    WORKFLOWS_DIRECTORY = Path(".github/workflows")
    """
    Where GitHub Actions finds a repository's workflows.
    """


# %% a Python project's files


class PythonProjectFile(PathEnumeration):
    """
    The files and directories a Python project lays itself out with, relative to its
    root.
    """

    PYPROJECT = Path("pyproject.toml")
    """
    The project's settings, which may name the members of its uv workspace.
    """

    UV_LOCK = Path("uv.lock")
    """
    The versions uv pins the project's environment to, there when uv manages it.
    """

    SOURCE_DIRECTORY = Path("src")
    """
    Where a project laid out with a source directory keeps its packages.
    """
