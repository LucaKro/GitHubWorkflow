"""
Tests for :mod:`basstler_domain_model.environment`.
"""

from __future__ import annotations

import pytest
from basstler_domain_model.environment import GitVariable, ShellVariable

# %% git's variables


def test_an_assignment_to_a_git_variable_steers_git() -> None:
    assert GitVariable.steers_git(f"{GitVariable.INDEX_FILE}=/tmp/index")


def test_a_variable_outside_git_s_does_not_steer_git() -> None:
    assert not GitVariable.steers_git("HOME=/tmp")


# %% the shell's variables


def test_the_command_search_path_is_read_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ShellVariable.COMMAND_SEARCH_PATH, "/opt/tools")

    assert ShellVariable.COMMAND_SEARCH_PATH.read() == "/opt/tools"
