"""
Tests for :mod:`basstler_domain_model.environment`.
"""

from __future__ import annotations

from basstler_domain_model.environment import GitVariable

# %% git's variables


def test_an_assignment_to_a_git_variable_steers_git() -> None:
    assert GitVariable.steers_git(f"{GitVariable.INDEX_FILE}=/tmp/index")


def test_a_variable_outside_git_s_does_not_steer_git() -> None:
    assert not GitVariable.steers_git("HOME=/tmp")
