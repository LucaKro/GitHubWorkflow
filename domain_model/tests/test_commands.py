"""
Tests for :mod:`domain_model.commands`: a command's result, whether or not it could run.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from domain_model.commands import CommandRunner

from .dataset.locations import DatasetLocation

# %% running


def test_a_finished_command_keeps_its_output(tmp_path):
    result = CommandRunner(tmp_path).run(sys.executable, "-c", "print('done')")

    assert result.succeeded
    assert result.output == "done"


def test_a_failing_command_keeps_its_status_and_error_output(tmp_path):
    result = CommandRunner(tmp_path).run(
        sys.executable, "-c", "import sys; sys.exit('broken')"
    )

    assert result.exit_status == 1
    assert result.error_output == "broken"


def test_a_command_that_is_not_installed_comes_back_as_a_result(tmp_path):
    result = CommandRunner(tmp_path).run("a-command-that-does-not-exist")

    assert not result.succeeded
    assert result.exit_status is None


def test_a_command_that_runs_too_long_comes_back_unfinished(tmp_path: Path) -> None:
    result = CommandRunner(tmp_path).run(
        sys.executable, str(DatasetLocation.SLEEPING_SCRIPT), timeout_seconds=0.2
    )

    assert result.exit_status is None


def test_a_command_cannot_be_run_without_a_program(tmp_path) -> None:
    with pytest.raises(TypeError):
        CommandRunner(tmp_path).run()
