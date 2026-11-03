"""
Install the runtime the plugin's hooks run: a virtual environment holding this plugin's
own copy of the workflow and the pinned domain model, built beside the one in use and
switched over to only once its guard works. A runtime built from this plugin, as its
content is now, is left alone.

Runs on the standard library alone, before any runtime exists, so it is run as a file
rather than imported from the package. A step that fails ends it with the step and what
the step said; the runtime in use is left as it was.

Installs one at a time: an install started while another runs waits for it, and finds
the runtime current when that one built it.

Usage: ``python3 install.py [--background] <plugin directory> <runtime path>``; prints
one line when it installed, or started installing in a process of its own, nothing when
the runtime already came from this plugin.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
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


class Requirement(StrEnum):
    """
    What the runtime installs besides the plugin itself.
    """

    DOMAIN_MODEL = "basstler-domain-model @ git+https://github.com/LucaKro/basstler_domain_model@f019ccf690026f578db579ccf24d6fea0a6f7e46"
    """
    The shared GitHub and git model, public, which no index serves, pinned to one
    commit so that only a change here changes what a runtime runs.
    """


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
    The plugin's directory, which is also the workflow's source.
    """

    location: Path
    """
    The runtime's path.
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
                name
                for name in subdirectories
                if name not in UnstampedDirectory._value2member_map_
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
        created = self._ran([sys.executable, "-m", "venv", str(build)])
        if created is None or created.returncode != 0:
            shutil.rmtree(build)
            build.mkdir()
            self._run(
                ["virtualenv", "--quiet", "-p", sys.executable, str(build)], build
            )
        pip = [str(python), "-I", "-m", "pip", "install", "--quiet"]
        self._run([*pip, Requirement.DOMAIN_MODEL], build)
        self._run([*pip, str(self.plugin)], build)
        push = {"tool_name": "Bash", "tool_input": {"command": "git push"}}
        checked = subprocess.run(
            [str(python), "-I", "-m", "github_workflow.guard"],
            input=json.dumps(push),
            capture_output=True,
            text=True,
        )
        if '"deny"' not in checked.stdout:
            self._fail("checking the new runtime's guard", checked, build)
        (build / RuntimeFile.PLUGIN).write_text(stamp)
        RuntimeSwitch(self.location).to(build)
        return f"github-workflow: runtime installed from the plugin at {self.plugin}"

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
