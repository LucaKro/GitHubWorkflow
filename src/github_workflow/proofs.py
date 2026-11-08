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
from basstler_domain_model.git.branch_tips import BranchTip
from basstler_domain_model.git.commands import GitCommandRunner, RemoteBranch
from basstler_domain_model.github.issue_models import IssueComment
from basstler_domain_model.templates import Placeholder

from github_workflow.checkout import ProjectCheckout
from github_workflow.environment import PythonVariable
from github_workflow.exceptions import (
    BrokenTestError,
    FileOutsideCheckoutError,
    PassingTestError,
)
from github_workflow.locations import ProofFile, WorkflowTemplate
from github_workflow.workspace import PackageDirectories

# %% the template's placeholders


class ProofPlaceholder(Placeholder):
    """
    The names the proof comment's template leaves to be filled in.
    """

    RECORD = auto()
    """
    A proof as the record its comment carries, between its markers.
    """

    BRANCH = auto()
    """
    The branch a finding's test failed on.
    """

    COMMIT = auto()
    """
    The commit it failed on.
    """

    FAILURE = auto()
    """
    pytest's message on the failure.
    """

    PATH = auto()
    """
    The test's path in the repository.
    """

    FENCE = auto()
    """
    The backticks fencing the test's text, more than any run of them inside it.
    """

    SOURCE = auto()
    """
    The test's text.
    """


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

    def misses_its_own_file(self, message: str) -> bool:
        """
        :param message: pytest's message on a failure of this test.
        :return: Whether it failed only because a file under the test's own top
            directory, such as its data, is missing from the copy it ran in.
        """
        if len(self.path.parts) < 2:
            return False
        exception, _, said = message.partition(":")
        missing = said.rpartition(": ")[2].strip("'\"")
        own = exception == MissingFileException.FILE_NOT_FOUND_ERROR
        return own and f"/{self.path.parts[0]}/" in missing

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
    A finding's test, run once on a branch.
    """

    test: FindingTest
    """
    The test.
    """

    tip: BranchTip
    """
    The branch's commit it ran on.
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
        broken = [
            *self.errors,
            *filter(BrokenTestException.reported_in, self.failures),
            *filter(test.misses_its_own_file, self.failures),
        ]
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
    Runs a finding's test on a branch, the default branch unless told otherwise.
    """

    @abstractmethod
    def attempt(self, test: FindingTest) -> ProofAttempt:
        """
        :param test: The test.
        :return: How it fared on the branch's latest commit.
        """


@dataclass(frozen=True)
class BranchProofRunner(ProofRunner):
    """
    Runs a finding's test on a branch as GitHub has it now, in a scratch copy of its
    files: the default branch, or the branch of the pull request a draft builds on.
    """

    git: GitCommandRunner
    """
    The checkout, which only fetches; its files are left alone.
    """

    remote: str
    """
    The owner's remote, holding the branch.
    """

    branch: str
    """
    The branch the test runs on.
    """

    python: str
    """
    The interpreter the project's tests run with.
    """

    def attempt(self, test: FindingTest) -> ProofAttempt:
        """
        Overrides :meth:`ProofRunner.attempt`: the branch is fetched from GitHub
        first, and its packages are imported from its commit rather than from
        wherever the interpreter installed them.

        :raises GitCommandFailed: If the branch cannot be fetched.
        """
        branch = RemoteBranch(self.remote, self.branch)
        fetched = self.git.fetch_branch(branch)
        fetched.raise_if_failed()
        tip = BranchTip(branch.name, self.git.commit_at(branch.tracking_reference))
        with tempfile.TemporaryDirectory() as directory:
            files = Path(directory) / ProofFile.DEFAULT_BRANCH
            self.git.export_files(tip.commit, files)
            (files / test.path).parent.mkdir(parents=True, exist_ok=True)
            (files / test.path).write_text(test.source)
            report = Path(directory) / ProofFile.REPORT
            search_path = PackageDirectories(files).search_path()
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

    def to_json(self) -> dict[str, str]:
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
        record = json.dumps(self.to_json()).replace(">", "\\u003e")
        backtick_runs = re.findall("`+", self.test.source)
        fence = "`" * max([3, *(len(run) + 1 for run in backtick_runs)])
        return Placeholder.fill(
            WorkflowTemplate.PROOF_COMMENT.read_text(),
            {
                ProofPlaceholder.RECORD: (
                    f"{ProofMarker.START}{record}{ProofMarker.END}"
                ),
                ProofPlaceholder.BRANCH: self.tip.branch,
                ProofPlaceholder.COMMIT: self.tip.commit,
                ProofPlaceholder.FAILURE: self.failure,
                ProofPlaceholder.PATH: str(self.test.path),
                ProofPlaceholder.FENCE: fence,
                ProofPlaceholder.SOURCE: self.test.source.rstrip("\n"),
            },
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
