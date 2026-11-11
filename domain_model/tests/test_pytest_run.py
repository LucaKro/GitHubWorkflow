"""
Tests for :mod:`domain_model.pytest_run`: running pytest on a test file and reading its
report.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from domain_model.pytest_run import (
    BrokenTestException,
    JUnitReport,
    PytestRun,
)

from .dataset.locations import DatasetLocation

# %% the report


def test_a_report_counts_its_tests_and_names_each_failure_by_its_first_line():
    report = JUnitReport.from_xml(DatasetLocation.JUNIT_REPORT_WITH_FAILURE.read_text())

    assert report == JUnitReport(2, ("AssertionError: assert 1 == 2",), ())


def test_a_broken_test_s_exception_is_recognised():
    assert BrokenTestException.is_reported(f"{BrokenTestException.NAME_ERROR}: x")


# %% running pytest


def test_a_run_reports_the_failing_test(tmp_path: Path):
    test = Path("test_copied.py")
    shutil.copy(DatasetLocation.FAILING_TEST_FILE, tmp_path / test)

    result = PytestRun(
        sys.executable, tmp_path, test, tmp_path / "report.xml", []
    ).run()

    assert (result.report.test_count, len(result.report.failures)) == (1, 1)
