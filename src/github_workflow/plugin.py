"""
The plugin: the distributions it ships, the source directories a runtime is built from,
the repository it comes from, the modules a runtime runs, and the launcher running the
workflow from a runtime.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum, IntEnum, StrEnum
from pathlib import Path

from domain_model.code_version import CodeVersion
from domain_model.environment import ShellVariable

from github_workflow.locations import PluginDirectory, RuntimeLocation

# %% what the plugin ships


class Distribution(StrEnum):
    """
    The distributions the workflow runs, by the names ``pip`` installs them under.
    """

    WORKFLOW = "github-workflow"
    """
    The workflow itself.
    """

    DOMAIN_MODEL = CodeVersion.distribution_name
    """
    The model of git and GitHub the workflow is built on.
    """


class PluginSource(Enum):
    """
    The source directories in the plugin a runtime runs, each copied into the runtime
    under its distribution's name.
    """

    WORKFLOW = (PluginDirectory.WORKFLOW_SOURCE, Distribution.WORKFLOW)
    """
    The workflow's own source.
    """

    DOMAIN_MODEL = (PluginDirectory.DOMAIN_MODEL_SOURCE, Distribution.DOMAIN_MODEL)
    """
    The domain model's source, shipped with the plugin.
    """

    def __init__(self, path: PluginDirectory, distribution: Distribution) -> None:
        """
        :param path: The directory, relative to the plugin's.
        :param distribution: The distribution it holds, which names its copy.
        """
        self.path = path
        self.distribution = distribution

    @classmethod
    def search_path(cls, plugin: Path) -> str:
        """
        :param plugin: The plugin's directory.
        :return: Every source directory in it, as a module search path.
        """
        return os.pathsep.join(str(plugin / source.path) for source in cls)


class ToolRepository(StrEnum):
    """
    The repositories the workflow is built from, as ``owner/name``; the domain model is
    shipped in the workflow's.
    """

    WORKFLOW = "LucaKro/GitHubWorkflow"
    """
    The workflow itself: the guard, the hooks and the commands.
    """

    @property
    def owner(self) -> str:
        """:return: The account the repository belongs to."""
        return self.partition("/")[0]

    @property
    def url(self) -> str:
        """:return: The repository's page on GitHub, which git also fetches from."""
        return f"https://github.com/{self}"


# %% what a runtime runs


class RuntimeModule(StrEnum):
    """
    The modules a runtime's interpreter runs.
    """

    COMMANDS = "github_workflow"
    """
    The workflow's commands.
    """

    RUNTIME_CHECK = "github_workflow.runtime_check"
    """
    The check a new runtime passes before it is switched over to.
    """


class FileMode(IntEnum):
    """
    The modes the workflow writes a file it runs with.
    """

    RUNNABLE = 0o755
    """
    Readable and runnable by everyone, writable by its owner.
    """


# %% the launcher


class Launcher(StrEnum):
    """
    The command running the workflow from its runtime, on the person's path.
    """

    COMMAND = Distribution.WORKFLOW.value
    """
    The command's name, as the person types it: the workflow's own.
    """

    MARKER = f"# Written by {Distribution.WORKFLOW}'s runtime install."
    """
    The line marking a launcher as the workflow's own.
    """


@dataclass(frozen=True)
class LauncherInstallation:
    """
    The launcher, running the workflow with one runtime's interpreter.
    """

    directory: Path
    """
    Where the launcher is written.
    """

    runtime: Path
    """
    The runtime it runs the workflow with.
    """

    @property
    def script(self) -> str:
        """
        The launcher, as written.
        """
        interpreter = self.runtime / RuntimeLocation.INTERPRETER
        return (
            f"#!/bin/sh\n{Launcher.MARKER}\n"
            f'exec "{interpreter}" -I -m {RuntimeModule.COMMANDS} "$@"\n'
        )

    def install(self) -> str | None:
        """
        Write the launcher, replacing an earlier one of the workflow's, but never a file
        of the same name that is not.

        :return: Why the person cannot run it yet, ``None`` when they can.
        """
        path = self.directory / Launcher.COMMAND
        if path.exists() and Launcher.MARKER not in path.read_text():
            return f"left {path} alone, which is not the workflow's"
        self.directory.mkdir(parents=True, exist_ok=True)
        path.write_text(self.script)
        path.chmod(FileMode.RUNNABLE)
        searched = (ShellVariable.COMMAND_SEARCH_PATH.read() or "").split(os.pathsep)
        if str(self.directory) not in searched:
            return f"add {self.directory} to PATH to run {Launcher.COMMAND}"
        return None
