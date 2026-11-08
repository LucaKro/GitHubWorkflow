"""
Running pytest on a test file, and what its JUnit XML report says about how the tests
fared.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from xml.etree import ElementTree

from domain_model.commands import CommandRunner
from domain_model.environment import PythonVariable

# %% how a test fared


class MissingFileException(StrEnum):
    """
    The exception a test fails with when a file it opens is not there.
    """

    FILE_NOT_FOUND_ERROR = "FileNotFoundError"
    """
    Python's exception for a file that is not there.
    """


class BrokenTestException(StrEnum):
    """
    The exceptions a test fails with when the test itself is broken, rather than the
    code it tests.
    """

    IMPORT_ERROR = "ImportError"
    """
    A name the test imports does not exist.
    """

    MODULE_NOT_FOUND_ERROR = "ModuleNotFoundError"
    """
    A module the test imports does not exist.
    """

    NAME_ERROR = "NameError"
    """
    The test uses a name it never defined or imported.
    """

    UNBOUND_LOCAL_ERROR = "UnboundLocalError"
    """
    The test reads a local variable before assigning it.
    """

    SYNTAX_ERROR = "SyntaxError"
    """
    The test is not valid Python.
    """

    INDENTATION_ERROR = "IndentationError"
    """
    The test is indented wrongly.
    """

    @classmethod
    def reported_in(cls, message: str) -> bool:
        """
        :param message: pytest's message on a failed test.
        :return: Whether it reports one of these exceptions.
        """
        return message.partition(":")[0] in cls


class JUnitElement(StrEnum):
    """
    The elements of pytest's JUnit XML report that are read.
    """

    TEST_CASE = "testcase"
    """
    One test, or one module that could not be collected.
    """

    FAILURE = "failure"
    """
    Inside a test case: the test failed.
    """

    ERROR = "error"
    """
    Inside a test case: the test could not be collected or set up.
    """


class JUnitAttribute(StrEnum):
    """
    The attributes of pytest's JUnit XML report that are read.
    """

    MESSAGE = "message"
    """
    pytest's message on a failure or error.
    """


@dataclass(frozen=True)
class JUnitReport:
    """
    One pytest run, as its JUnit XML report records it.
    """

    test_count: int
    """
    How many tests ran or could not be collected.
    """

    failures: tuple[str, ...]
    """
    The first line of pytest's message on each failed test.
    """

    errors: tuple[str, ...]
    """
    The first line of pytest's message on each test that could not be collected or set
    up.
    """

    @classmethod
    def from_xml(cls, text: str) -> JUnitReport:
        """
        :param text: The report.
        :return: What it records.
        """
        cases = list(ElementTree.fromstring(text).iter(JUnitElement.TEST_CASE))
        return cls(
            len(cases),
            cls.messages(cases, JUnitElement.FAILURE),
            cls.messages(cases, JUnitElement.ERROR),
        )

    @staticmethod
    def messages(
        cases: Sequence[ElementTree.Element], element: JUnitElement
    ) -> tuple[str, ...]:
        """
        :param cases: The report's test cases.
        :param element: The kind of outcome to read.
        :return: The first line of the message of each outcome of that kind, followed
            by the last line of pytest's report on it when that adds to it, such as the
            exception a module could not be collected with.
        """
        described = []
        for case in cases:
            for outcome in case.iter(element):
                message = outcome.get(JUnitAttribute.MESSAGE, "").partition("\n")[0]
                reported = (outcome.text or "").strip().splitlines()
                last = reported[-1].strip() if reported else ""
                adds = last and last not in message and element is JUnitElement.ERROR
                described.append(f"{message}: {last}" if adds else message)
        return tuple(described)


class PytestOption(StrEnum):
    """
    The options pytest is run with.
    """

    JUNIT_XML = "--junitxml"
    """
    Where pytest writes its JUnit XML report.
    """


# %% running pytest


@dataclass(frozen=True)
class PytestResult:
    """
    One pytest run: its report, or why it wrote none.
    """

    report: JUnitReport | None
    """
    What the run's report records, None when pytest wrote none.
    """

    summary: str
    """
    The run's own summary of how it ended.
    """


@dataclass(frozen=True)
class PytestRun:
    """
    One test file run with pytest in a directory, importing packages first from the
    directories given.
    """

    python: str
    """
    The interpreter pytest runs with.
    """

    directory: Path
    """
    Where pytest runs.
    """

    test: Path
    """
    The test file, relative to the directory.
    """

    report: Path
    """
    Where pytest writes its JUnit XML report.
    """

    search_path: Sequence[str]
    """
    The directories packages are imported from, before the interpreter's own.
    """

    def run(self) -> PytestResult:
        """
        :return: How the run went.
        """
        search_path = list(self.search_path)
        inherited = PythonVariable.MODULE_SEARCH_PATH.read()
        if inherited:
            search_path.append(inherited)
        ran = CommandRunner(self.directory).run(
            self.python,
            "-m",
            "pytest",
            f"{PytestOption.JUNIT_XML}={self.report}",
            str(self.test),
            environment={
                PythonVariable.MODULE_SEARCH_PATH: os.pathsep.join(search_path)
            },
        )
        if not self.report.exists():
            return PytestResult(None, ran.summary)
        return PytestResult(JUnitReport.from_xml(self.report.read_text()), ran.summary)
