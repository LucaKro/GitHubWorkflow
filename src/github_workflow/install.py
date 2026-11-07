"""
Install the runtime the plugin's hooks run: a virtual environment holding this plugin's
copy of the workflow's source and the domain model's source at its pinned commit, switched
over to once its guard denies a push and its commands load; one install at a time, a
runtime built from this plugin as it is now left alone. Runs on the standard library.

Usage: ``python3 install.py [--background] <plugin directory> <runtime path>``; prints
one line when it installed, or started installing in a process of its own, nothing when
the runtime already came from this plugin.
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

# %% vocabulary


class RuntimeFile(StrEnum):
    """
    The file inside a runtime that says which plugin it was built from.
    """

    PLUGIN = "github-workflow-plugin"
    """
    Holds the directory of the plugin the runtime was built from, and a digest of its
    content.
    """

    SOURCE_PATHS = "github-workflow.pth"
    """
    Lists the source directories the runtime's interpreter imports from, in its
    site-packages.
    """


class Distribution(StrEnum):
    """
    The distributions the workflow runs, by the names ``pip`` installs them under.
    """

    WORKFLOW = "github-workflow"
    """
    The workflow itself.
    """

    DOMAIN_MODEL = "basstler-domain-model"
    """
    The model of git and GitHub the workflow is built on.
    """


class RuntimeSource(StrEnum):
    """
    The directories inside a runtime holding the source it runs, each named after its
    distribution.
    """

    WORKFLOW = Distribution.WORKFLOW.value
    """
    The plugin's own copy of the workflow's source.
    """

    DOMAIN_MODEL = Distribution.DOMAIN_MODEL.value
    """
    A checkout of the domain model at its pinned commit.
    """


class RuntimeDirectory(StrEnum):
    """
    The directories inside a runtime the installer creates.
    """

    SOURCES = "sources"
    """
    Holds every :class:`RuntimeSource`.
    """


class UnstampedDirectory(StrEnum):
    """
    The directories in a plugin whose content is not part of what a runtime is built
    from.
    """

    GIT = ".git"
    """
    The plugin's history, when it is a checkout.
    """

    BYTECODE = "__pycache__"
    """
    Compiled modules, written as the plugin's code runs.
    """


class ToolRepository(StrEnum):
    """
    The repositories the workflow is built from, as ``owner/name``.
    """

    WORKFLOW = "LucaKro/GitHubWorkflow"
    """
    The workflow itself: the guard, the hooks and the commands.
    """

    DOMAIN_MODEL = "LucaKro/basstler_domain_model"
    """
    The model of git and GitHub the workflow is built on.
    """

    @property
    def owner(self) -> str:
        """:return: The account the repository belongs to."""
        return self.partition("/")[0]

    @property
    def url(self) -> str:
        """:return: The repository's page on GitHub, which git also fetches from."""
        return f"https://github.com/{self}"


class DomainModelSource(StrEnum):
    """
    The commit the runtime and the Actions workflows take the domain model's source at.
    """

    COMMIT = "4dd8c9af90e51d07167e30e7c98e6d933736caa4"
    """
    The commit it is pinned to.
    """


class InstallOption(StrEnum):
    """
    The installer's command-line options.
    """

    BACKGROUND = "--background"
    """
    Install in a process of its own and return at once.
    """


# %% the launcher


class Launcher(StrEnum):
    """
    The command running the workflow from its runtime, on the person's path.
    """

    COMMAND = "github-workflow"
    """
    The command's name, as the person types it.
    """

    DIRECTORY = ".local/bin"
    """
    Where it is written, under the home directory: the usual place for one's own
    commands.
    """

    MARKER = "# Written by github-workflow's runtime install."
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
        interpreter = self.runtime / "bin" / "python"
        return (
            f"#!/bin/sh\n{Launcher.MARKER}\n"
            f'exec "{interpreter}" -I -m github_workflow "$@"\n'
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
        path.chmod(0o755)
        searched = os.environ.get("PATH", "").split(os.pathsep)
        if str(self.directory) not in searched:
            return f"add {self.directory} to PATH to run {Launcher.COMMAND}"
        return None


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
    The plugin's directory, which is also the workflow's source.
    """

    location: Path
    """
    The runtime's path.
    """

    launcher_directory: Path = field(
        default_factory=lambda: Path.home() / Launcher.DIRECTORY
    )
    """
    Where the launcher running the workflow from the runtime is written.
    """

    @property
    def stamp(self) -> str:
        """
        What a runtime built from this plugin records: the plugin's directory, and a
        digest of its content, the domain model's pin among it.
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
        stamp = self.location / RuntimeFile.PLUGIN
        return stamp.exists() and stamp.read_text() == self.stamp

    def start(self) -> str | None:
        """
        Start :meth:`install` in a process of its own that outlives this one, unless the
        runtime already came from this plugin.

        :return: What is being installed, ``None`` when nothing is.
        """
        if self.current:
            return None
        subprocess.Popen(
            [sys.executable, "-I", __file__, str(self.plugin), str(self.location)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return (
            f"github-workflow: installing the runtime from the plugin at {self.plugin}"
        )

    def install(self) -> str | None:
        """
        Build the runtime from this plugin and switch over to it, unless it already came
        from this plugin, once no other install runs.

        :return: What was installed, ``None`` when nothing was.
        """
        self.location.parent.mkdir(parents=True, exist_ok=True)
        with DirectoryLock(self.location.parent):
            if self.current:
                return None
            return self._build()

    def _build(self) -> str:
        """
        Build the runtime from this plugin and switch over to it.

        :return: What was installed.
        """
        stamp = self.stamp
        build = Path(
            tempfile.mkdtemp(prefix=f".{self.location.name}-", dir=self.location.parent)
        )
        python = build / "bin" / "python"
        created = self._ran([sys.executable, "-m", "venv", "--without-pip", str(build)])
        if created is None or created.returncode != 0:
            shutil.rmtree(build)
            build.mkdir()
            self._run(
                ["virtualenv", "--quiet", "--no-pip", "-p", sys.executable, str(build)],
                build,
            )
        sources = build / RuntimeDirectory.SOURCES
        workflow = sources / RuntimeSource.WORKFLOW
        shutil.copytree(
            self.plugin / "src",
            workflow,
            ignore=shutil.ignore_patterns(UnstampedDirectory.BYTECODE),
        )
        domain_model = sources / RuntimeSource.DOMAIN_MODEL
        domain_model.mkdir(parents=True)
        git = ["git", "-C", str(domain_model)]
        self._run([*git, "init", "--quiet"], build)
        self._run(
            [
                *git,
                "fetch",
                "--quiet",
                "--depth=1",
                ToolRepository.DOMAIN_MODEL.url,
                DomainModelSource.COMMIT,
            ],
            build,
        )
        self._run([*git, "checkout", "--quiet", "FETCH_HEAD"], build)
        site_packages = Path(
            sysconfig.get_path(
                "purelib", "venv", {"base": str(build), "platbase": str(build)}
            )
        )
        site_packages.mkdir(parents=True, exist_ok=True)
        (site_packages / RuntimeFile.SOURCE_PATHS).write_text(
            f"{workflow}\n{domain_model / 'src'}\n"
        )
        checked = subprocess.run(
            [str(python), "-I", "-m", "github_workflow.runtime_check"],
            capture_output=True,
            text=True,
        )
        if checked.returncode != 0:
            self._fail("checking the new runtime", checked, build)
        (build / RuntimeFile.PLUGIN).write_text(stamp)
        RuntimeSwitch(self.location).to(build)
        installed = (
            f"github-workflow: runtime installed from the plugin at {self.plugin}"
        )
        launcher = LauncherInstallation(
            self.launcher_directory, self.location
        ).install()
        return installed if launcher is None else f"{installed}; {launcher}"

    def _run(self, command: list[str], build: Path) -> None:
        """
        :param command: One step of the build.
        :param build: The build, removed when the step fails.
        """
        finished = self._ran(command)
        if finished is None or finished.returncode != 0:
            self._fail(" ".join(command[:4]), finished, build)

    @staticmethod
    def _ran(command: list[str]) -> subprocess.CompletedProcess[str] | None:
        """
        :param command: One step of the build.
        :return: The finished step, its output kept, ``None`` when its program is not
            there.
        """
        if shutil.which(command[0]) is None:
            return None
        return subprocess.run(command, capture_output=True, text=True)

    @staticmethod
    def _fail(
        step: str, finished: subprocess.CompletedProcess[str] | None, build: Path
    ) -> None:
        """
        :param step: The step that failed.
        :param finished: What it said, ``None`` when its program is not there.
        :param build: The build, removed.
        :raises SystemExit: Always, with the step and the last line it said.
        """
        shutil.rmtree(build, ignore_errors=True)
        said = (finished.stderr or finished.stdout).splitlines() if finished else []
        raise SystemExit(
            f"installing the runtime failed at {step}: {''.join(said[-1:])}"
        )


# %% entry point


def main() -> None:
    """
    Install the runtime the command line names from the plugin it names.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument(InstallOption.BACKGROUND, action="store_true")
    parser.add_argument("plugin", type=Path)
    parser.add_argument("location", type=Path)
    arguments = parser.parse_args()
    installation = RuntimeInstallation(arguments.plugin.resolve(), arguments.location)
    installed = installation.start() if arguments.background else installation.install()
    if installed is not None:
        print(installed)


if __name__ == "__main__":
    main()
