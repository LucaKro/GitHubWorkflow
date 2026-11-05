"""
Where a Python project's packages are imported from, its uv workspace's members
included.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from github_workflow.locations import ProjectFile

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
        file = self.root / ProjectFile.PYPROJECT
        if not file.exists():
            return []
        tool = tomllib.loads(file.read_text()).get(WorkspaceKey.TOOL, {})
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
