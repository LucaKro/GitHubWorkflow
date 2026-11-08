"""
Install the runtime the plugin's hooks run: a virtual environment holding a copy of this
plugin's workflow and domain model source, switched over to once its guard denies a push
and its commands load; one install at a time, a runtime built from this plugin as it is
now left alone. Runs with the system's interpreter on the plugin's own source, and
downloads nothing.

Usage: ``python3 -I -c 'import sys; sys.path[:0] = sys.argv.pop(1).split(":"); from
github_workflow.install import main; main()' <source directories> [--background]
<plugin directory> <runtime path>``; prints one line when it installed, or started
installing in a process of its own, nothing when the runtime already came from this
plugin.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import os
import shutil
import subprocess
import sys
import sysconfig
import tempfile
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from domain_model.commands import CommandResult, CommandRunner

from github_workflow.exceptions import RuntimeInstallError
from github_workflow.locations import (
    HomeDirectory,
    RuntimeLocation,
    SitePackagesFile,
    UnstampedDirectory,
)
from github_workflow.plugin import LauncherInstallation, PluginSource, RuntimeModule
from github_workflow.report_lines import FailureReport, Speaker

# %% the command line


class InstallOption(StrEnum):
    """
    The installer's command-line options.
    """

    BACKGROUND = "--background"
    """
    Install in a process of its own and return at once.
    """


# %% switching over


@dataclass(frozen=True)
class RuntimeSwitch:
    """
    The path the hooks run the runtime from, pointed at one build after another.
    """

    location: Path
    """
    The runtime's path, which ends up a link to the build in use.
    """

    def to(self, build: Path) -> None:
        """
        Point the runtime's path at a build in one step, and remove the build it pointed
        at before.

        :param build: The new build, beside the runtime's path.
        """
        previous: Path | None = None
        if self.location.is_symlink():
            previous = self.location.parent / os.readlink(self.location)
        elif self.location.exists():
            previous = self.location.with_name(f".{self.location.name}-retired")
            self.location.rename(previous)
        link = self.location.with_name(f".{self.location.name}-link")
        link.unlink(missing_ok=True)
        link.symlink_to(build.name)
        os.replace(link, self.location)
        if previous is not None and previous.resolve() != build.resolve():
            shutil.rmtree(previous, ignore_errors=True)


# %% one install at a time


@dataclass
class DirectoryLock:
    """
    An exclusive lock on a directory, held while the ``with`` block runs; taking it
    waits until no other process holds it.
    """

    directory: Path
    """
    The directory locked.
    """

    descriptor: int | None = None
    """
    The directory opened while the lock is held, ``None`` otherwise.
    """

    def __enter__(self) -> DirectoryLock:
        self.descriptor = os.open(self.directory, os.O_RDONLY)
        fcntl.flock(self.descriptor, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exception: object) -> None:
        os.close(self.descriptor)
        self.descriptor = None


# %% installing


@dataclass(frozen=True)
class RuntimeInstallation:
    """
    The runtime built from one plugin directory.
    """

    plugin: Path
    """
    The plugin's directory, which holds the source the runtime is built from.
    """

    location: Path
    """
    The runtime's path.
    """

    launcher_directory: Path = field(
        default_factory=lambda: Path.home() / HomeDirectory.LAUNCHERS
    )
    """
    Where the launcher running the workflow from the runtime is written.
    """

    @property
    def stamp(self) -> str:
        """
        What a runtime built from this plugin records: the plugin's directory, and a
        digest of its content, the domain model's source among it.
        """
        files = []
        for directory, subdirectories, names in os.walk(self.plugin):
            subdirectories[:] = [
                name for name in subdirectories if name not in UnstampedDirectory
            ]
            files += [Path(directory) / name for name in names]
        digest = hashlib.sha256()
        for path in sorted(files):
            digest.update(f"{path.relative_to(self.plugin)}\0".encode())
            digest.update(path.read_bytes())
        return f"{self.plugin}\n{digest.hexdigest()}"

    @property
    def current(self) -> bool:
        """
        :return: Whether the runtime in use was built from this plugin, as its content
            is now.
        """
        stamp = self.location / RuntimeLocation.PLUGIN_STAMP
        return stamp.exists() and stamp.read_text() == self.stamp

    def start(self) -> str | None:
        """
        Start :meth:`install` in a process of its own that outlives this one, run on
        the plugin's own source, unless the runtime already came from this plugin.

        :return: What is being installed, ``None`` when nothing is.
        """
        if self.current:
            return None
        code = (
            f"import sys; sys.path[:0] = sys.argv.pop(1).split({os.pathsep!r}); "
            f"from {__name__} import main; main()"
        )
        subprocess.Popen(
            [
                sys.executable,
                "-I",
                "-c",
                code,
                PluginSource.search_path(self.plugin),
                str(self.plugin),
                str(self.location),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return Speaker.WORKFLOW.says(
            f"installing the runtime from the plugin at {self.plugin}"
        )

    def install(self) -> str | None:
        """
        Build the runtime from this plugin and switch over to it, unless it already came
        from this plugin, once no other install runs.

        :return: What was installed, ``None`` when nothing was.
        :raises RuntimeInstallError: If a step of the build fails; the runtime in use
            is left alone.
        """
        self.location.parent.mkdir(parents=True, exist_ok=True)
        with DirectoryLock(self.location.parent):
            if self.current:
                return None
            return self.build()

    def build(self) -> str:
        """
        Build the runtime from this plugin and switch over to it.

        :return: What was installed.
        :raises RuntimeInstallError: If a step of the build fails.
        """
        stamp = self.stamp
        build = Path(
            tempfile.mkdtemp(prefix=f".{self.location.name}-", dir=self.location.parent)
        )
        runner = CommandRunner(self.location.parent)
        created = runner.run(sys.executable, "-m", "venv", "--without-pip", str(build))
        if not created.succeeded:
            shutil.rmtree(build)
            build.mkdir()
            self.raise_if_failed(
                runner.run(
                    "virtualenv",
                    "--quiet",
                    "--no-pip",
                    "-p",
                    sys.executable,
                    str(build),
                ),
                build,
            )
        sources = build / RuntimeLocation.SOURCES
        copies = [sources / source.distribution for source in PluginSource]
        for source, copy in zip(PluginSource, copies):
            shutil.copytree(
                self.plugin / source.path,
                copy,
                ignore=shutil.ignore_patterns(UnstampedDirectory.BYTECODE),
            )
        site_packages = Path(
            sysconfig.get_path(
                "purelib", "venv", {"base": str(build), "platbase": str(build)}
            )
        )
        site_packages.mkdir(parents=True, exist_ok=True)
        (site_packages / SitePackagesFile.SOURCE_PATHS).write_text(
            "".join(f"{copy}\n" for copy in copies)
        )
        interpreter = build / RuntimeLocation.INTERPRETER
        checked = runner.run(str(interpreter), "-I", "-m", RuntimeModule.RUNTIME_CHECK)
        self.raise_if_failed(checked, build, "checking the new runtime")
        (build / RuntimeLocation.PLUGIN_STAMP).write_text(stamp)
        RuntimeSwitch(self.location).to(build)
        installed = Speaker.WORKFLOW.says(
            f"runtime installed from the plugin at {self.plugin}"
        )
        launcher = LauncherInstallation(
            self.launcher_directory, self.location
        ).install()
        return installed if launcher is None else f"{installed}; {launcher}"

    @staticmethod
    def raise_if_failed(
        finished: CommandResult, build: Path, step: str | None = None
    ) -> None:
        """
        :param finished: One step of the build.
        :param build: The build, removed when the step failed.
        :param step: The step, as the refusal names it; its first words when ``None``.
        :raises RuntimeInstallError: If the step failed.
        """
        if finished.succeeded:
            return
        shutil.rmtree(build, ignore_errors=True)
        said = (finished.error_output or finished.output).splitlines()
        raise RuntimeInstallError(
            step or " ".join(finished.arguments[:4]), "".join(said[-1:])
        )


# %% entry point


def main() -> None:
    """
    Install the runtime the command line names from the plugin it names.
    """
    sys.excepthook = FailureReport(speaker=None).report
    parser = argparse.ArgumentParser()
    parser.add_argument(InstallOption.BACKGROUND, action="store_true")
    parser.add_argument("plugin", type=Path)
    parser.add_argument("location", type=Path)
    arguments = parser.parse_args()
    installation = RuntimeInstallation(arguments.plugin.resolve(), arguments.location)
    installed = installation.start() if arguments.background else installation.install()
    if installed is not None:
        print(installed)
