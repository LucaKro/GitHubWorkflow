"""
Install the runtime the plugin's hooks run: a virtual environment holding this plugin's
own copy of the workflow and the domain model, built beside the one in use and switched
over to only once its guard works. A runtime built from this plugin already is left
alone.

Runs on the standard library alone, before any runtime exists, so it is run as a file
rather than imported from the package. A step that fails ends it with the step and what
the step said; the runtime in use is left as it was.

Usage: ``python3 install.py <plugin directory> <runtime path>``; prints one line when it
installed, nothing when the runtime already came from this plugin.
"""

from __future__ import annotations

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
    Holds the directory of the plugin the runtime was built from.
    """


class Requirement(StrEnum):
    """
    What the runtime installs besides the plugin itself.
    """

    DOMAIN_MODEL = "basstler-domain-model @ git+https://github.com/LucaKro/basstler_domain_model@main"
    """
    The shared GitHub and git model, public, which no index serves.
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
        Point the runtime's path at a build in one step, and remove the build it
        pointed at before.

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
    def current(self) -> bool:
        """:return: Whether the runtime in use was built from this plugin."""
        stamp = self.location / RuntimeFile.PLUGIN
        return stamp.exists() and stamp.read_text() == str(self.plugin)

    def install(self) -> str | None:
        """
        Build the runtime from this plugin and switch over to it, unless it already
        came from this plugin.

        :return: What was installed, ``None`` when nothing was.
        """
        if self.current:
            return None
        self.location.parent.mkdir(parents=True, exist_ok=True)
        build = Path(
            tempfile.mkdtemp(prefix=f".{self.location.name}-", dir=self.location.parent)
        )
        python = build / "bin" / "python"
        if not self._ran([sys.executable, "-m", "venv", str(build)], build, quiet=True):
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
        (build / RuntimeFile.PLUGIN).write_text(str(self.plugin))
        RuntimeSwitch(self.location).to(build)
        return f"github-workflow: runtime installed from the plugin at {self.plugin}"

    def _run(self, command: list[str], build: Path) -> None:
        """
        :param command: One step of the build.
        :param build: The build, removed when the step fails.
        """
        if not self._ran(command, build):
            self._fail(" ".join(command[:4]), None, build)

    @staticmethod
    def _ran(command: list[str], build: Path, quiet: bool = False) -> bool:
        """
        :param command: One step of the build.
        :param build: The build the step works on.
        :param quiet: Whether to keep the step's output to itself, for a step whose
            failure is expected.
        :return: Whether the step succeeded; a program that is not there fails it.
        """
        if shutil.which(command[0]) is None:
            return False
        finished = subprocess.run(
            command,
            capture_output=quiet,
            stdout=None if quiet else subprocess.DEVNULL,
            text=True,
        )
        return finished.returncode == 0

    @staticmethod
    def _fail(
        step: str, finished: subprocess.CompletedProcess[str] | None, build: Path
    ) -> None:
        """
        :param step: The step that failed.
        :param finished: What it said, when it was captured.
        :param build: The build, removed.
        :raises SystemExit: Always, with the step and its last line.
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
    installed = RuntimeInstallation(
        Path(sys.argv[1]).resolve(), Path(sys.argv[2])
    ).install()
    if installed is not None:
        print(installed)


if __name__ == "__main__":
    main()
