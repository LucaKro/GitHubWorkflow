"""
Tests for :mod:`github_workflow.session_start` and the hook running it: a slow section
costs only its own line, and the hook keeps one marker per session, named after it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from basstler_domain_model.locations import PathEnumeration

from github_workflow.environment import WorkflowVariable
from github_workflow.hooks import Tone
from github_workflow.report import SectionName
from github_workflow.session_start import SessionStart
from github_workflow.settings import WorkflowSettings

from .repositories_by_owner import RepositoriesByOwner

# %% the dataset


class SessionDataset(PathEnumeration):
    """
    The files the session start is tried with.
    """

    SLOW_SECTION = Path(__file__).parent / "dataset" / "session" / "slow_section.sh"
    """
    Stands in for the interpreter computing a section, and never finishes in time.
    """

    HOOK_SCRIPT = Path(__file__).parents[1] / "hooks" / "session-start.sh"
    """
    The hook the plugin runs.
    """


# %% a slow section


def test_a_section_running_out_of_time_costs_one_red_line(
    repositories: RepositoriesByOwner,
    owned_url: str,
    settings: WorkflowSettings,
    monkeypatch: pytest.MonkeyPatch,
):
    start = SessionStart(repositories.clone(owned_url, "session"), settings)
    monkeypatch.setattr(sys, "executable", str(SessionDataset.SLOW_SECTION.value))
    started = time.monotonic()

    lines = start.section(SectionName.SETUP, timeout_seconds=0.5)

    assert time.monotonic() - started < 5
    assert [line.tone for line in lines] == [Tone.PROBLEM]


# %% the hook


def run_hook(
    tmp_path: Path,
    session: str,
    event: str = "SessionStart",
    variables: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """
    Run the hook with a plugin lacking the installer, so it reports the failed install
    and nothing is downloaded.

    :param tmp_path: The scratch directory, taken as the temporary directory.
    :param session: The session's identifier.
    :param event: The hook event.
    :param variables: What Claude Code sets for the hook besides the plugin's root.
    :return: The finished hook.
    """
    return subprocess.run(
        [str(SessionDataset.HOOK_SCRIPT.value), event],
        input=json.dumps({"session_id": session}),
        capture_output=True,
        text=True,
        env={
            "PATH": os.environ["PATH"],
            "HOME": str(tmp_path / "home"),
            "TMPDIR": str(tmp_path),
            "CLAUDE_PLUGIN_ROOT": str(tmp_path / "plugin"),
            **(variables or {}),
        },
    )


def markers(tmp_path: Path) -> list[Path]:
    """
    :param tmp_path: The temporary directory the hook ran with.
    :return: The marker of every session reported.
    """
    return sorted(tmp_path.glob("*/*"))


def test_the_session_s_commands_are_told_where_the_plugin_s_data_is(tmp_path: Path):
    commands_environment = tmp_path / "environment.sh"
    data = tmp_path / "plugin data"

    run_hook(
        tmp_path,
        "session",
        variables={
            "CLAUDE_ENV_FILE": str(commands_environment),
            "CLAUDE_PLUGIN_DATA": str(data),
        },
    )

    command = subprocess.run(
        ["bash", "-c", 'source "$1" && printenv "$2"', "bash"]
        + [str(commands_environment), WorkflowVariable.PLUGIN_DATA],
        capture_output=True,
        text=True,
        check=True,
    )
    assert command.stdout.rstrip("\n") == str(data)


def test_a_session_s_marker_is_named_after_its_identifier(tmp_path: Path):
    run_hook(tmp_path, 'a"b')

    assert [marker.name for marker in markers(tmp_path)] == ['a"b']


def test_the_markers_of_sessions_long_over_are_removed(tmp_path: Path):
    run_hook(tmp_path, "over")
    [over] = markers(tmp_path)
    a_month_ago = time.time() - 30 * 24 * 60 * 60
    os.utime(over, (a_month_ago, a_month_ago))

    run_hook(tmp_path, "current")

    assert [marker.name for marker in markers(tmp_path)] == ["current"]
