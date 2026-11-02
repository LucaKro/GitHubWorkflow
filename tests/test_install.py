"""
Tests for :mod:`github_workflow.install`: a runtime is built from a plugin only when the
one in use came from another, and a build that fails leaves the runtime in use alone.
"""

from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

import pytest

import github_workflow.install
from github_workflow.install import (
    DirectoryLock,
    RuntimeFile,
    RuntimeInstallation,
    RuntimeSwitch,
)

# %% which plugin a runtime came from


def built_from(location: Path, plugin: Path) -> Path:
    """:param location: Where the runtime is.
    :param plugin: The plugin it was built from.
    :return: The runtime, a directory that says so."""
    location.mkdir(parents=True)
    (location / RuntimeFile.PLUGIN).write_text(str(plugin))
    return location


def test_a_runtime_built_from_this_plugin_is_current(tmp_path: Path):
    plugin = tmp_path / "plugin"
    runtime = built_from(tmp_path / "runtime", plugin)

    assert RuntimeInstallation(plugin, runtime).current


def test_a_runtime_built_from_another_plugin_is_not(tmp_path: Path):
    runtime = built_from(tmp_path / "runtime", tmp_path / "old-plugin")

    assert not RuntimeInstallation(tmp_path / "new-plugin", runtime).current


def test_no_runtime_is_not_current(tmp_path: Path):
    assert not RuntimeInstallation(tmp_path / "plugin", tmp_path / "runtime").current


def test_a_current_runtime_is_not_built_again(tmp_path: Path):
    plugin = tmp_path / "plugin"
    runtime = built_from(tmp_path / "environments" / "runtime", plugin)

    assert RuntimeInstallation(plugin, runtime).install() is None
    assert [path.name for path in runtime.parent.iterdir()] == [runtime.name]


# %% a failing build


def test_a_failing_build_leaves_the_runtime_in_use_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """
    An interpreter that does not exist fails the very first step, before any download.
    """
    runtime = built_from(tmp_path / "environments" / "runtime", tmp_path / "old")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "no-interpreter"))

    with pytest.raises(SystemExit):
        RuntimeInstallation(tmp_path / "new", runtime).install()

    assert [path.name for path in runtime.parent.iterdir()] == [runtime.name]
    assert (runtime / RuntimeFile.PLUGIN).read_text() == str(tmp_path / "old")


# %% one install at a time


def test_an_install_waits_for_the_one_running_and_takes_its_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """
    An interpreter that does not exist makes an install that does not wait fail at once,
    so a running install is what keeps it waiting.
    """
    plugin = tmp_path / "plugin"
    runtime = tmp_path / "environments" / "runtime"
    runtime.parent.mkdir()
    monkeypatch.setattr(sys, "executable", str(tmp_path / "no-interpreter"))
    installed: list[str | None] = []
    waiting = threading.Thread(
        target=lambda: installed.append(RuntimeInstallation(plugin, runtime).install())
    )

    with DirectoryLock(runtime.parent):
        waiting.start()
        waiting.join(timeout=0.5)
        assert waiting.is_alive()
        built_from(runtime, plugin)
    waiting.join()

    assert installed == [None]


def test_a_current_runtime_is_not_started_again(tmp_path: Path):
    plugin = tmp_path / "plugin"
    runtime = built_from(tmp_path / "environments" / "runtime", plugin)

    assert RuntimeInstallation(plugin, runtime).start() is None


def test_a_started_install_runs_this_installer_on_its_own(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    plugin = tmp_path / "plugin"
    runtime = tmp_path / "runtime"
    started: list[list[str]] = []
    monkeypatch.setattr(
        subprocess, "Popen", lambda command, **options: started.append(command)
    )

    RuntimeInstallation(plugin, runtime).start()

    assert started == [
        [
            sys.executable,
            "-I",
            github_workflow.install.__file__,
            str(plugin),
            str(runtime),
        ]
    ]


# %% switching over


def test_the_first_switch_turns_the_runtime_into_a_link_to_the_build(tmp_path: Path):
    location = tmp_path / "runtime"
    location.mkdir()
    build = tmp_path / ".runtime-build"
    build.mkdir()

    RuntimeSwitch(location).to(build)

    assert location.resolve() == build.resolve()
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        ".runtime-build",
        "runtime",
    ]


def test_a_later_switch_moves_the_link_and_removes_the_build_before(tmp_path: Path):
    location = tmp_path / "runtime"
    first = tmp_path / ".runtime-first"
    second = tmp_path / ".runtime-second"
    first.mkdir()
    second.mkdir()
    location.symlink_to(first.name)

    RuntimeSwitch(location).to(second)

    assert location.resolve() == second.resolve()
    assert not first.exists()


def test_a_switch_where_no_runtime_was_creates_the_link(tmp_path: Path):
    build = tmp_path / ".runtime-build"
    build.mkdir()

    RuntimeSwitch(tmp_path / "runtime").to(build)

    assert (tmp_path / "runtime").resolve() == build.resolve()
