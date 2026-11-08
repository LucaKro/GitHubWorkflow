"""
A Python project as its files lay it out: its settings, the directories its packages and
its uv workspace's members are imported from, and the tool managing its environment.
"""

from __future__ import annotations

import tomllib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from basstler_domain_model.locations import PythonProjectFile

# %% the project's settings


class ProjectKey(StrEnum):
    """
    The keys of a ``pyproject.toml``'s ``[project]`` table read here.
    """

    PROJECT = "project"
    """
    The table itself.
    """

    OPTIONAL_DEPENDENCIES = "optional-dependencies"
    """
    The project's extras, each with its dependencies.
    """


@dataclass(frozen=True)
class Pyproject:
    """
    A Python project's ``pyproject.toml``.
    """

    root: Path
    """
    The project's root.
    """

    def settings(self) -> dict[str, Any]:
        """
        :return: Its tables, none when the project has no ``pyproject.toml``.
        """
        file = self.root / PythonProjectFile.PYPROJECT
        return tomllib.loads(file.read_text()) if file.exists() else {}


# %% the workspace's members


class WorkspaceKey(StrEnum):
    """
    The keys leading to, and inside, the table of a uv workspace's root
    ``pyproject.toml`` naming its members: ``[tool.uv.workspace]``.
    """

    TOOL = "tool"
    """
    The table every tool's settings are in.
    """

    UV = "uv"
    """
    uv's table in it.
    """

    WORKSPACE = "workspace"
    """
    The workspace's table in that.
    """

    MEMBERS = "members"
    """
    The patterns matching the members' directories.
    """

    EXCLUDE = "exclude"
    """
    The patterns matching directories that are no members after all.
    """


@dataclass(frozen=True)
class PackageDirectories:
    """
    The directories a Python project's packages are imported from: for the project and
    each member of its uv workspace, its source directory when it has one, otherwise
    its own directory.
    """

    root: Path
    """
    The project's root.
    """

    def search_path(self) -> list[str]:
        """
        :return: The directories, the project's own first.
        """
        projects = [self.root, *self.workspace_members()]
        return [
            str(
                project / PythonProjectFile.SOURCE_DIRECTORY
                if (project / PythonProjectFile.SOURCE_DIRECTORY).is_dir()
                else project
            )
            for project in projects
        ]

    def workspace_members(self) -> list[Path]:
        """
        :return: The directories of its uv workspace's members, in the order its
            patterns name them, none when it is no workspace.
        """
        tool = Pyproject(self.root).settings().get(WorkspaceKey.TOOL, {})
        workspace = tool.get(WorkspaceKey.UV, {}).get(WorkspaceKey.WORKSPACE, {})
        excluded = {
            directory
            for pattern in workspace.get(WorkspaceKey.EXCLUDE, [])
            for directory in self.root.glob(pattern)
        }
        members = [
            directory
            for pattern in workspace.get(WorkspaceKey.MEMBERS, [])
            for directory in sorted(self.root.glob(pattern))
            if directory.is_dir() and directory not in excluded
        ]
        return list(dict.fromkeys(members))


# %% the tool managing its environment


class DevelopmentExtra(StrEnum):
    """
    The names a project's extras for development and testing go by.
    """

    DEV = "dev"
    """
    Everything needed to develop it.
    """

    TEST = "test"
    """
    What its tests need.
    """

    TESTS = "tests"
    """
    What its tests need, by the other common name.
    """


@dataclass(frozen=True)
class EnvironmentTool(ABC):
    """
    A tool a project manages its Python environment with.
    """

    executable: str
    """
    The command the tool runs as.
    """

    @abstractmethod
    def manages(self, root: Path) -> bool:
        """
        :param root: A project's root.
        :return: Whether the project declares this tool manages its environment.
        """

    @abstractmethod
    def setup_command(self, root: Path) -> str:
        """
        :param root: A project's root.
        :return: The command setting its environment up for development and tests.
        """


@dataclass(frozen=True)
class UvTool(EnvironmentTool):
    """
    uv, declared by a ``uv.lock`` or a ``[tool.uv]`` table.
    """

    executable: str = "uv"
    """
    The program the tool is run as.
    """

    def manages(self, root: Path) -> bool:
        if (root / PythonProjectFile.UV_LOCK).exists():
            return True
        return WorkspaceKey.UV in Pyproject(root).settings().get(WorkspaceKey.TOOL, {})

    def setup_command(self, root: Path) -> str:
        extras = (
            Pyproject(root)
            .settings()
            .get(ProjectKey.PROJECT, {})
            .get(ProjectKey.OPTIONAL_DEPENDENCIES, {})
        )
        named = [f"--extra {extra}" for extra in DevelopmentExtra if extra in extras]
        return " ".join([self.executable, "sync", *named])
