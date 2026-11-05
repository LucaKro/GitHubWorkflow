"""
Proofs of findings: a test that fails on the default branch as GitHub has it, posted on
the finding's issue rather than committed.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from abc import ABC, abstractmethod
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from enum import Enum, StrEnum, auto
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from basstler_domain_model.commands import CommandRunner
from basstler_domain_model.git.commands import GitCommandRunner, RemoteBranch
from basstler_domain_model.github.issue_models import IssueComment

from github_workflow.checkout import ProjectCheckout
from github_workflow.environment import PythonVariable
from github_workflow.exceptions import (
    BrokenTestError,
    FileOutsideCheckoutError,
    PassingTestError,
)
from github_workflow.locations import ProjectFile, ProofFile, WorkflowTemplate

# %% the test and where it ran


@dataclass(frozen=True)
class FindingTest:
    """
    A test file showing a finding, as it would be committed.
    """

    path: Path
    """
    Where it goes, relative to the repository's root.
    """

    source: str
    """
    Its text.
    """

    @classmethod
    def read(cls, checkout: ProjectCheckout, file: Path) -> FindingTest:
        """
        :param checkout: The checkout the test would be committed to.
        :param file: The test file.
        :return: The test, at its path in the repository.
        :raises FileOutsideCheckoutError: If the file is not inside the checkout.
        """
        located = file.resolve()
        root = checkout.root.resolve()
        if not located.is_relative_to(root):
            raise FileOutsideCheckoutError(str(file), str(root))
        return cls(located.relative_to(root), located.read_text())


@dataclass(frozen=True)
class BranchTip:
    """
    The commit a branch was at when it was read.
    """

    branch: str
    """
    The branch.
    """

    commit: str
    """
    The commit it was at.
    """

    def __str__(self) -> str:
        """:return: The branch and its commit, abbreviated."""
        return f"{self.branch} at {self.commit[:7]}"


# %% how a test fared


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


class ProofOutcome(Enum):
    """
    How a finding's test fared on the default branch.
    """

    FAILS = auto()
    """
    A test fails, and none is broken: the finding is proven.
    """

    PASSES = auto()
    """
    Every test passes: the default branch shows no finding.
    """

    BROKEN = auto()
    """
    No test ran, or one failed only because it is broken.
    """


@dataclass(frozen=True)
class ProofAttempt:
    """
    A finding's test, run once on the default branch.
    """

    test: FindingTest
    """
    The test.
    """

    tip: BranchTip
    """
    The default branch's commit it ran on.
    """

    outcome: ProofOutcome
    """
    How it fared.
    """

    message: str
    """
    pytest's message on the first failure or breakage, empty when every test passed.
    """

    def proof(self) -> Proof:
        """
        :return: The proof the attempt makes.
        :raises PassingTestError: If every test passed.
        :raises BrokenTestError: If the test is broken.
        """
        if self.outcome is ProofOutcome.PASSES:
            raise PassingTestError(str(self.test.path), self.tip)
        if self.outcome is ProofOutcome.BROKEN:
            raise BrokenTestError(str(self.test.path), self.message)
        return Proof(self.test, self.tip, self.message)


# %% pytest's report


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

    def attempt(self, test: FindingTest, tip: BranchTip) -> ProofAttempt:
        """
        :param test: The test the report is on.
        :param tip: The commit it ran on.
        :return: How the test fared.
        """
        broken = [*self.errors, *filter(BrokenTestException.reported_in, self.failures)]
        if broken:
            return ProofAttempt(test, tip, ProofOutcome.BROKEN, broken[0])
        if self.failures:
            return ProofAttempt(test, tip, ProofOutcome.FAILS, self.failures[0])
        if not self.test_count:
            return ProofAttempt(test, tip, ProofOutcome.BROKEN, "no test ran")
        return ProofAttempt(test, tip, ProofOutcome.PASSES, "")


class PytestOption(StrEnum):
    """
    The options pytest is run with.
    """

    JUNIT_XML = "--junitxml"
    """
    Where pytest writes its JUnit XML report.
    """


# %% running a test


class ProofRunner(ABC):
    """
    Runs a finding's test on the default branch.
    """

    @abstractmethod
    def attempt(self, test: FindingTest) -> ProofAttempt:
        """
        :param test: The test.
        :return: How it fared on the default branch's latest commit.
        """


@dataclass(frozen=True)
class DefaultBranchProofRunner(ProofRunner):
    """
    Runs a finding's test on the default branch as GitHub has it now, in a scratch copy
    of its files.
    """

    git: GitCommandRunner
    """
    The checkout, which only fetches; its files are left alone.
    """

    remote: str
    """
    The owner's remote, holding the default branch.
    """

    default_branch: str
    """
    The repository's default branch.
    """

    python: str
    """
    The interpreter the project's tests run with.
    """

    def attempt(self, test: FindingTest) -> ProofAttempt:
        """
        Overrides :meth:`ProofRunner.attempt`: the default branch is fetched from
        GitHub first, and its packages are imported from its commit rather than from
        wherever the interpreter installed them.

        :raises GitCommandFailed: If the default branch cannot be fetched.
        """
        branch = RemoteBranch(self.remote, self.default_branch)
        fetched = self.git.fetch_branch(branch)
        fetched.raise_if_failed()
        tip = BranchTip(branch.name, self.git.commit_at(branch.tracking_reference))
        with tempfile.TemporaryDirectory() as directory:
            files = Path(directory) / ProofFile.DEFAULT_BRANCH
            self.git.export_files(tip.commit, files)
            (files / test.path).parent.mkdir(parents=True, exist_ok=True)
            (files / test.path).write_text(test.source)
            report = Path(directory) / ProofFile.REPORT
            search_path = [str(files / ProjectFile.SOURCE_DIRECTORY)]
            if PythonVariable.MODULE_SEARCH_PATH.read():
                search_path.append(PythonVariable.MODULE_SEARCH_PATH.read())
            ran = CommandRunner(files).run(
                self.python,
                "-m",
                "pytest",
                f"{PytestOption.JUNIT_XML}={report}",
                str(test.path),
                environment={
                    PythonVariable.MODULE_SEARCH_PATH: os.pathsep.join(search_path)
                },
            )
            if not report.exists():
                return ProofAttempt(test, tip, ProofOutcome.BROKEN, ran.summary)
            return JUnitReport.from_xml(report.read_text()).attempt(test, tip)


# %% the proof posted on the issue


class ProofKey(StrEnum):
    """
    The keys of the record a proof comment carries.
    """

    PATH = "path"
    """
    The test's path in the repository.
    """

    SOURCE = "source"
    """
    The test's text.
    """

    BRANCH = "branch"
    """
    The default branch it failed on.
    """

    COMMIT = "commit"
    """
    The commit it failed on.
    """

    FAILURE = "failure"
    """
    pytest's message on the failure.
    """


class ProofMarker(StrEnum):
    """
    The text around the record a proof comment carries, hidden from a person reading
    it.
    """

    START = "<!-- github-workflow:proof "
    """
    Opens the record.
    """

    END = " -->"
    """
    Closes the record.
    """


class ProofPlaceholder(StrEnum):
    """
    The names the proof comment template leaves to be filled in.
    """

    RECORD = "__RECORD__"
    """
    The record, between its markers.
    """

    BRANCH = "__BRANCH__"
    """
    The default branch the test failed on.
    """

    COMMIT = "__COMMIT__"
    """
    The commit it failed on.
    """

    FAILURE = "__FAILURE__"
    """
    pytest's message on the failure.
    """

    PATH = "__PATH__"
    """
    The test's path in the repository.
    """

    FENCE = "__FENCE__"
    """
    The backticks fencing the test's text, more than any run of them inside it.
    """

    SOURCE = "__SOURCE__"
    """
    The test's text.
    """


@dataclass(frozen=True)
class Proof:
    """
    A finding's test, and how it failed on the default branch.
    """

    test: FindingTest
    """
    The test.
    """

    tip: BranchTip
    """
    The default branch's commit it failed on.
    """

    failure: str
    """
    The first line of pytest's message on the first failed test.
    """

    def json(self) -> dict[str, str]:
        """:return: The proof as the record its comment carries."""
        return {
            ProofKey.PATH: str(self.test.path),
            ProofKey.SOURCE: self.test.source,
            ProofKey.BRANCH: self.tip.branch,
            ProofKey.COMMIT: self.tip.commit,
            ProofKey.FAILURE: self.failure,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Proof:
        """
        :param data: The record a proof comment carries.
        :return: The proof.
        """
        return cls(
            FindingTest(Path(data[ProofKey.PATH]), data[ProofKey.SOURCE]),
            BranchTip(data[ProofKey.BRANCH], data[ProofKey.COMMIT]),
            data[ProofKey.FAILURE],
        )

    def comment(self) -> str:
        """
        :return: The comment posting the proof on the finding's issue, for a person to
            read and :meth:`posted_in` to read back.
        """
        record = json.dumps(self.json()).replace(">", "\\u003e")
        backtick_runs = re.findall("`+", self.test.source)
        fence = "`" * max([3, *(len(run) + 1 for run in backtick_runs)])
        values = {
            ProofPlaceholder.RECORD: f"{ProofMarker.START}{record}{ProofMarker.END}",
            ProofPlaceholder.BRANCH: self.tip.branch,
            ProofPlaceholder.COMMIT: self.tip.commit,
            ProofPlaceholder.FAILURE: self.failure,
            ProofPlaceholder.PATH: str(self.test.path),
            ProofPlaceholder.FENCE: fence,
            ProofPlaceholder.SOURCE: self.test.source.rstrip("\n"),
        }
        return re.sub(
            "|".join(map(re.escape, ProofPlaceholder)),
            lambda placeholder: values[ProofPlaceholder(placeholder.group())],
            WorkflowTemplate.PROOF_COMMENT.read_text(),
        )

    @classmethod
    def posted_in(
        cls, comments: Sequence[IssueComment], authors: Collection[str]
    ) -> Proof | None:
        """
        :param comments: An issue's comments, oldest first.
        :param authors: The logins whose proofs count, in any case.
        :return: The latest proof one of them posted, ``None`` when none did.
        """
        trusted = {author.casefold() for author in authors}
        for comment in reversed(comments):
            start = comment.body.find(ProofMarker.START)
            if comment.author.casefold() not in trusted or start == -1:
                continue
            record = comment.body[start + len(ProofMarker.START) :]
            return cls.from_json(json.loads(record.partition(ProofMarker.END)[0]))
        return None
