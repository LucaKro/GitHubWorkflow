"""
Where a Python project's packages are imported from, its uv workspace's members
included, and the tool it manages its environment with.
"""

from __future__ import annotations

import shutil
import tomllib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from github_workflow.command_line import CommandOption
from github_workflow.locations import ProjectFile
from github_workflow.report_lines import Audience, ReportLine, Speaker, Tone

# %% the project's settings


class ProjectKey(StrEnum):
    """
    The keys of a ``pyproject.toml``'s ``[project]`` table the workflow reads.
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
        file = self.root / ProjectFile.PYPROJECT
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
                project / ProjectFile.SOURCE_DIRECTORY
                if (project / ProjectFile.SOURCE_DIRECTORY).is_dir()
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
        if (root / ProjectFile.UV_LOCK).exists():
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


@dataclass(frozen=True)
class ProjectTooling:
    """
    What a session is told about the tool the project manages its environment with:
    to set the environment up with it whenever tests need it, never by hand. The
    workflow never runs the tool itself.
    """

    root: Path
    """
    The project's root.
    """

    tools: tuple[EnvironmentTool, ...] = (UvTool(),)
    """
    The tools looked for, in order; the first the project declares counts.
    """

    def lines(self) -> list[ReportLine]:
        """
        :return: How to set the environment up, or that the tool is missing; nothing
            when the project declares none of the tools.
        """
        tool = next((tool for tool in self.tools if tool.manages(self.root)), None)
        if tool is None:
            return []
        command = tool.setup_command(self.root)
        if shutil.which(tool.executable) is None:
            return [
                ReportLine(
                    Speaker.WORKFLOW.says(
                        f"this project's environment is managed with "
                        f"{tool.executable}, which is not installed, so `{command}` "
                        f"cannot set it up: ask the person whether to install it, and "
                        f"install none of the project's packages by hand"
                    ),
                    Tone.ACTION,
                )
            ]
        return [
            ReportLine(
                Speaker.WORKFLOW.says(
                    f"this project's environment is managed with {tool.executable}: "
                    f"whenever tests need it, set it up with `{command}` and run them "
                    f"in it, giving the workflow's proof commands its interpreter with "
                    f"`{CommandOption.PYTHON}`; never install the project's packages "
                    f"by hand"
                ),
                Tone.NEWS,
                Audience.MODEL,
            )
        ]
