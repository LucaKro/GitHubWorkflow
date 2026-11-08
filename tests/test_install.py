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
from domain_model.commands import CommandResult, CommandRunner
from domain_model.environment import ShellVariable
from domain_model.locations import PathEnumeration

import github_workflow
import github_workflow.install
from github_workflow.command_line import WorkflowCommand
from github_workflow.exceptions import RuntimeInstallError
from github_workflow.install import DirectoryLock, RuntimeInstallation, RuntimeSwitch
from github_workflow.locations import RuntimeLocation, UnstampedDirectory
from github_workflow.plugin import (
    FileMode,
    Launcher,
    LauncherInstallation,
    PluginSource,
    RuntimeModule,
)

# %% the dataset


class RuntimeDataset(PathEnumeration):
    """
    The files the installer is tried with.
    """

    FAILING_STEP = Path(__file__).parent / "dataset" / "runtime" / "failing_step.sh"
    """
    A build step that fails, saying why on its error output.
    """


# %% which plugin a runtime came from


def test_a_runtime_built_from_a_plugin_whose_content_changed_since_is_not_current(
    tmp_path: Path,
) -> None:
    plugin = tmp_path / "plugin"
    plugin.mkdir()
    (plugin / "module.py").write_text("before\n")
    runtime = built_from(tmp_path / "environments" / "runtime", plugin)
    (plugin / "module.py").write_text("after\n")

    assert not RuntimeInstallation(plugin, runtime).current


@pytest.mark.parametrize("directory", list(UnstampedDirectory))
def test_a_change_outside_what_the_runtime_is_built_from_keeps_it_current(
    tmp_path: Path, directory: UnstampedDirectory
) -> None:
    plugin = tmp_path / "plugin"
    (plugin / directory).mkdir(parents=True)
    runtime = built_from(tmp_path / "environments" / "runtime", plugin)
    (plugin / directory / "written").write_text("since\n")

    assert RuntimeInstallation(plugin, runtime).current


def built_from(location: Path, plugin: Path) -> Path:
    """:param location: Where the runtime is.
    :param plugin: The plugin it was built from.
    :return: The runtime, a directory that says so."""
    location.mkdir(parents=True)
    (location / RuntimeLocation.PLUGIN_STAMP).write_text(
        RuntimeInstallation(plugin, location).stamp
    )
    return location


def test_a_runtime_built_from_this_plugin_is_current(tmp_path: Path) -> None:
    plugin = tmp_path / "plugin"
    runtime = built_from(tmp_path / "runtime", plugin)

    assert RuntimeInstallation(plugin, runtime).current


def test_a_runtime_built_from_another_plugin_is_not(tmp_path: Path) -> None:
    runtime = built_from(tmp_path / "runtime", tmp_path / "old-plugin")

    assert not RuntimeInstallation(tmp_path / "new-plugin", runtime).current


def test_no_runtime_is_not_current(tmp_path: Path) -> None:
    assert not RuntimeInstallation(tmp_path / "plugin", tmp_path / "runtime").current


def test_a_current_runtime_is_not_built_again(tmp_path: Path) -> None:
    plugin = tmp_path / "plugin"
    runtime = built_from(tmp_path / "environments" / "runtime", plugin)

    assert RuntimeInstallation(plugin, runtime).install() is None
    assert [path.name for path in runtime.parent.iterdir()] == [runtime.name]


# %% a failing build


def test_a_failing_build_leaves_the_runtime_in_use_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    An interpreter that does not exist fails the very first step, before any download.
    """
    runtime = built_from(tmp_path / "environments" / "runtime", tmp_path / "old")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "no-interpreter"))

    with pytest.raises(RuntimeInstallError):
        RuntimeInstallation(tmp_path / "new", runtime).install()

    assert [path.name for path in runtime.parent.iterdir()] == [runtime.name]
    assert (runtime / RuntimeLocation.PLUGIN_STAMP).read_text() == (
        RuntimeInstallation(tmp_path / "old", runtime).stamp
    )


def test_a_failing_step_is_reported_with_what_it_said_on_its_error_output(
    tmp_path: Path,
) -> None:
    build = tmp_path / "build"
    build.mkdir()

    finished = CommandRunner(tmp_path).run(str(RuntimeDataset.FAILING_STEP))

    with pytest.raises(RuntimeInstallError) as failed:
        RuntimeInstallation.raise_if_failed(finished, build)

    assert (failed.value.said, build.exists()) == ("the reason the step failed", False)


# %% building without a package index


def test_a_runtime_is_built_without_pip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    pip reaches a package index for the build tools of both packages, which a session's
    network may not allow. Every command a build starts is recorded and succeeds;
    creating a virtual environment leaves an interpreter in it, and the new guard denies
    a push.
    """
    started: list[list[str]] = []

    def run(
        runner: CommandRunner, program: str, *arguments: str, **options: object
    ) -> CommandResult:
        started.append([program, *arguments])
        return builds(program, *arguments)

    monkeypatch.setattr(CommandRunner, "run", run)

    RuntimeInstallation(
        Path(github_workflow.install.__file__).parents[2],
        tmp_path / "runtime",
        tmp_path / "bin",
    ).install()

    assert [command for command in started if "pip" in command] == []


def test_a_runtime_is_built_without_downloading_the_domain_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    The domain model is shipped with the plugin, so a build runs no git command, which
    a session's network or a commit gone from GitHub would make fail.
    """
    started: list[list[str]] = []

    def run(
        runner: CommandRunner, program: str, *arguments: str, **options: object
    ) -> CommandResult:
        started.append([program, *arguments])
        return builds(program, *arguments)

    monkeypatch.setattr(CommandRunner, "run", run)

    RuntimeInstallation(
        Path(github_workflow.install.__file__).parents[2],
        tmp_path / "runtime",
        tmp_path / "bin",
    ).install()

    assert [command for command in started if command[0] == "git"] == []


def builds(program: str, *arguments: str) -> CommandResult:
    """
    Stands in for every command a build starts: each succeeds, and creating a virtual
    environment leaves an interpreter in it.

    :param program: The program started.
    :param arguments: Its arguments.
    :return: How it finished.
    """
    if arguments[:2] == ("-m", "venv"):
        interpreter = Path(arguments[-1]) / RuntimeLocation.INTERPRETER
        interpreter.parent.mkdir(parents=True, exist_ok=True)
        interpreter.symlink_to(sys.executable)
    return CommandResult((program, *arguments), 0, "", "", 0.0)


def builds_commands_check_fails(
    runner: CommandRunner, program: str, *arguments: str, **options: object
) -> CommandResult:
    """
    Stands in for every command a build starts as :func:`builds` does, except that
    checking the new runtime fails, as with a domain model too old for the workflow's
    commands.

    :param runner: The runner starting it.
    :param program: The program started.
    :param arguments: Its arguments.
    :param options: How it is started.
    :return: How it finished.
    """
    if RuntimeModule.RUNTIME_CHECK in arguments:
        return CommandResult((program, *arguments), 1, "", "ImportError: too old", 0.0)
    return builds(program, *arguments)


def test_a_runtime_whose_commands_do_not_load_is_not_switched_to(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(CommandRunner, "run", builds_commands_check_fails)

    with pytest.raises(RuntimeInstallError):
        RuntimeInstallation(
            Path(github_workflow.install.__file__).parents[2],
            tmp_path / "runtime",
            tmp_path / "bin",
        ).install()

    assert not (tmp_path / "runtime").exists()


def test_a_runtime_built_from_the_plugin_runs_its_commands(tmp_path: Path) -> None:
    """
    Builds a runtime for real, so source the runtime cannot run fails here rather than
    in a session.
    """
    RuntimeInstallation(
        Path(github_workflow.install.__file__).parents[2],
        tmp_path / "runtime",
        tmp_path / "bin",
    ).install()

    finished = subprocess.run(
        [
            str(tmp_path / "runtime" / RuntimeLocation.INTERPRETER),
            "-I",
            "-m",
            github_workflow.__name__,
            "--help",
        ],
        capture_output=True,
        text=True,
    )

    assert finished.returncode == 0


# %% the launcher


def test_the_launcher_runs_the_workflow_from_the_runtime(tmp_path: Path) -> None:
    """
    A runtime whose interpreter hands over to this one, which has the workflow
    installed.
    """
    runtime = tmp_path / "runtime"
    interpreter = runtime / RuntimeLocation.INTERPRETER
    interpreter.parent.mkdir(parents=True)
    interpreter.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    interpreter.chmod(FileMode.RUNNABLE)
    LauncherInstallation(tmp_path / "bin", runtime).install()

    ran = subprocess.run(
        [str(tmp_path / "bin" / Launcher.COMMAND), "--help"],
        capture_output=True,
        text=True,
    )

    assert ran.returncode == 0


def test_a_file_of_the_launcher_s_name_that_is_not_the_workflow_s_is_left_alone(
    tmp_path: Path,
) -> None:
    (tmp_path / "bin").mkdir()
    own = tmp_path / "bin" / Launcher.COMMAND
    own.write_text("#!/bin/sh\necho mine\n")

    LauncherInstallation(tmp_path / "bin", tmp_path / "runtime").install()

    assert own.read_text() == "#!/bin/sh\necho mine\n"


def test_an_earlier_launcher_of_the_workflow_s_is_replaced(tmp_path: Path) -> None:
    LauncherInstallation(tmp_path / "bin", tmp_path / "old").install()
    newer = LauncherInstallation(tmp_path / "bin", tmp_path / "new")

    newer.install()

    assert (tmp_path / "bin" / Launcher.COMMAND).read_text() == newer.script


@pytest.mark.parametrize("on_path", [True, False])
def test_a_launcher_outside_the_path_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, on_path: bool
) -> None:
    directory = tmp_path / "bin"
    monkeypatch.setenv(
        ShellVariable.COMMAND_SEARCH_PATH, str(directory) if on_path else "/usr/bin"
    )

    said = LauncherInstallation(directory, tmp_path / "runtime").install()

    assert (said is None) == on_path


# %% one install at a time


def test_an_install_waits_for_the_one_running_and_takes_its_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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


def test_a_current_runtime_is_not_started_again(tmp_path: Path) -> None:
    plugin = tmp_path / "plugin"
    runtime = built_from(tmp_path / "environments" / "runtime", plugin)

    assert RuntimeInstallation(plugin, runtime).start() is None


def test_a_started_install_runs_the_installer_from_the_plugin_s_own_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    The command started, run itself on a runtime built from the plugin since, finds the
    installer in the plugin's source and has nothing to install.
    """
    plugin = Path(github_workflow.install.__file__).parents[2]
    runtime = tmp_path / "runtime"
    started: list[list[str]] = []
    with monkeypatch.context() as starting:
        starting.setattr(
            subprocess, "Popen", lambda command, **options: started.append(command)
        )
        RuntimeInstallation(plugin, runtime).start()
    built_from(runtime, plugin)

    [command] = started
    finished = subprocess.run(command, capture_output=True, text=True)

    assert (finished.returncode, finished.stdout) == (0, "")


def test_the_installer_runs_on_the_standard_library_and_the_plugin_s_source() -> None:
    """
    Without the interpreter's own packages, as the system's interpreter may have none.
    """
    plugin = Path(github_workflow.install.__file__).parents[2]

    finished = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-c",
            "import sys; sys.path[:0] = sys.argv.pop(1).split(':'); "
            f"import {github_workflow.install.__name__}",
            PluginSource.search_path(plugin),
        ],
        capture_output=True,
        text=True,
    )

    assert (finished.returncode, finished.stderr) == (0, "")


# %% switching over


def test_the_first_switch_turns_the_runtime_into_a_link_to_the_build(
    tmp_path: Path,
) -> None:
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


def test_a_later_switch_moves_the_link_and_removes_the_build_before(
    tmp_path: Path,
) -> None:
    location = tmp_path / "runtime"
    first = tmp_path / ".runtime-first"
    second = tmp_path / ".runtime-second"
    first.mkdir()
    second.mkdir()
    location.symlink_to(first.name)

    RuntimeSwitch(location).to(second)

    assert location.resolve() == second.resolve()
    assert not first.exists()


def test_a_switch_where_no_runtime_was_creates_the_link(tmp_path: Path) -> None:
    build = tmp_path / ".runtime-build"
    build.mkdir()

    RuntimeSwitch(tmp_path / "runtime").to(build)

    assert (tmp_path / "runtime").resolve() == build.resolve()


# %% command lines naming the launcher


def test_a_command_line_names_the_launcher_running_this_interpreter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    LauncherInstallation(tmp_path / "bin", Path(sys.executable).parents[1]).install()
    monkeypatch.setenv(ShellVariable.COMMAND_SEARCH_PATH, str(tmp_path / "bin"))

    assert WorkflowCommand.command_line(WorkflowCommand.PUSH) == (
        f"{Launcher.COMMAND} {WorkflowCommand.PUSH}"
    )


def test_a_launcher_running_another_interpreter_is_not_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    LauncherInstallation(tmp_path / "bin", tmp_path / "another-runtime").install()
    monkeypatch.setenv(ShellVariable.COMMAND_SEARCH_PATH, str(tmp_path / "bin"))

    assert WorkflowCommand.command_line(WorkflowCommand.PUSH).startswith(sys.executable)
