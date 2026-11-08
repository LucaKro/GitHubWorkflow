"""
Proofs of findings: a test that fails on the default branch as GitHub has it, posted on
the finding's issue rather than committed.
"""

from __future__ import annotations

import json
import re
import tempfile
from abc import ABC, abstractmethod
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from enum import Enum, StrEnum, auto
from pathlib import Path
from typing import Any

from basstler_domain_model.git.branch_tips import BranchTip
from basstler_domain_model.git.commands import GitCommandRunner, RemoteBranch
from basstler_domain_model.github.issue_models import IssueComment
from basstler_domain_model.pytest_run import (
    BrokenTestException,
    JUnitReport,
    MissingFileException,
    PytestRun,
)
from basstler_domain_model.python_project import PackageDirectories
from basstler_domain_model.templates import Placeholder

from github_workflow.checkout import ProjectCheckout
from github_workflow.exceptions import (
    BrokenTestError,
    FileOutsideCheckoutError,
    PassingTestError,
)
from github_workflow.locations import ProofFile, WorkflowTemplate

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

    @classmethod
    def from_report(
        cls, report: JUnitReport, test: FindingTest, tip: BranchTip
    ) -> ProofAttempt:
        """
        :param report: The report of a run of the test.
        :param test: The test.
        :param tip: The commit it ran on.
        :return: How the test fared.
        """
        broken = [
            *report.errors,
            *filter(BrokenTestException.reported_in, report.failures),
            *filter(test.misses_its_own_file, report.failures),
        ]
        if broken:
            return cls(test, tip, ProofOutcome.BROKEN, broken[0])
        if report.failures:
            return cls(test, tip, ProofOutcome.FAILS, report.failures[0])
        if not report.test_count:
            return cls(test, tip, ProofOutcome.BROKEN, "no test ran")
        return cls(test, tip, ProofOutcome.PASSES, "")

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
            result = PytestRun(
                self.python,
                files,
                test.path,
                Path(directory) / ProofFile.REPORT,
                PackageDirectories(files).search_path(),
            ).run()
            if result.report is None:
                return ProofAttempt(test, tip, ProofOutcome.BROKEN, result.summary)
            return ProofAttempt.from_report(result.report, test, tip)


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
