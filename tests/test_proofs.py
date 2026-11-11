"""
Tests for :mod:`github_workflow.proofs`: a finding's test runs on the default branch as
GitHub has it, proves the finding only when it fails for a reason other than being
broken, and is posted as a comment that reads back only from a trusted author.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from domain_model.environment import PythonVariable
from domain_model.git.remotes import Remote, RemoteName
from domain_model.git.revisions import CommitHash
from domain_model.github.issue_models import IssueComment
from domain_model.locations import PathEnumeration, PythonProjectFile

from github_workflow.checkout import ProjectCheckout
from github_workflow.exceptions import (
    BrokenTestError,
    FileOutsideCheckoutError,
    PassingTestError,
)
from github_workflow.proofs import (
    BranchProofRunner,
    BranchTip,
    FindingTest,
    Proof,
    ProofOutcome,
)
from github_workflow.settings import WorkflowSettings

from .repositories_by_owner import RepositoriesByOwner

# %% the dataset


class ProofDataset(PathEnumeration):
    """
    A package that doubles numbers, and tests run against it.
    """

    DOUBLING_CORRECT = (
        Path(__file__).parent / "dataset" / "proofs" / "doubling_correct.py"
    )
    """
    The package, doubling correctly.
    """

    DOUBLING_WRONG = Path(__file__).parent / "dataset" / "proofs" / "doubling_wrong.py"
    """
    The package, tripling where it should double.
    """

    DOUBLING_SHOWN_WRONG = (
        Path(__file__).parent / "dataset" / "proofs" / "doubling_shown_wrong.py"
    )
    """
    A test failing on the wrong package and passing on the correct one.
    """

    MISSPELT_IMPORT = (
        Path(__file__).parent / "dataset" / "proofs" / "misspelt_import.py"
    )
    """
    A test failing only on its own misspelt import.
    """

    UNCOLLECTABLE_MODULE = (
        Path(__file__).parent / "dataset" / "proofs" / "uncollectable_module.py"
    )
    """
    A test module whose import fails before any test is collected.
    """

    NO_TESTS = Path(__file__).parent / "dataset" / "proofs" / "no_tests.py"
    """
    A test module holding no test.
    """

    READS_MISSING_DATA = (
        Path(__file__).parent / "dataset" / "proofs" / "reads_missing_data.py"
    )
    """
    A test failing only because a data file beside it is missing.
    """

    CODE_MISSES_A_FILE = (
        Path(__file__).parent / "dataset" / "proofs" / "code_misses_a_file.py"
    )
    """
    A test failing because a file outside the tests is missing, as code under test
    could find it.
    """

    COMMENT_ENDS_AND_FENCES = (
        Path(__file__).parent / "dataset" / "proofs" / "comment_ends_and_fences.py"
    )
    """
    A module whose text holds a comment's end and a fence of four backticks.
    """

    WORKSPACE_PYPROJECT = (
        Path(__file__).parent / "dataset" / "proofs" / "workspace_pyproject.toml"
    )
    """
    The ``pyproject.toml`` of a uv workspace whose members are under ``packages``,
    but for ``packages/unused``.
    """


class DoublingProjectFile(PathEnumeration):
    """
    Where the doubling project keeps its files, relative to its root.
    """

    PACKAGE = PythonProjectFile.SOURCE_DIRECTORY / "doubling" / "__init__.py"
    """
    The package.
    """

    TEST = Path("tests") / "test_doubling.py"
    """
    The finding's test.
    """

    WORKSPACE_MEMBER = Path("packages") / "doubling"
    """
    The doubling package's directory, as a member of a uv workspace.
    """


# %% fixtures


@pytest.fixture
def checkout(repositories: RepositoriesByOwner, owned_url: str) -> ProjectCheckout:
    """:return: A clone of the owner's repository."""
    return repositories.clone(owned_url, "checkout")


def commit_package(checkout: ProjectCheckout, package: ProofDataset) -> None:
    """
    Commit a version of the doubling package on the checked-out branch.

    :param checkout: The checkout.
    :param package: The version.
    """
    target = checkout.root / DoublingProjectFile.PACKAGE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(package.read_text())
    checkout.git.run("add", str(DoublingProjectFile.PACKAGE))
    checkout.git.run("commit", "--quiet", "--message", "Doubling")


def publish_package(checkout: ProjectCheckout, package: ProofDataset) -> None:
    """
    Put a version of the doubling package on GitHub's default branch.

    :param checkout: A checkout on the default branch.
    :param package: The version.
    """
    commit_package(checkout, package)
    checkout.git.run(
        "push", "--quiet", RemoteName.ORIGIN, RepositoriesByOwner.default_branch
    )


def runner(
    checkout: ProjectCheckout, python: str = sys.executable
) -> BranchProofRunner:
    """
    :param checkout: The checkout.
    :param python: The interpreter the tests run with.
    :return: Runs tests on the checkout's default branch on GitHub.
    """
    [origin] = Remote.configured(checkout.git)
    return BranchProofRunner(origin.branch(RepositoriesByOwner.default_branch), python)


def finding_test(source: ProofDataset) -> FindingTest:
    """:param source: The test's text.
    :return: The test, where the doubling project keeps it."""
    return FindingTest(DoublingProjectFile.TEST, source.read_text())


def github_s_tip(checkout: ProjectCheckout) -> BranchTip:
    """:param checkout: The checkout.
    :return: Where GitHub's default branch is."""
    branch = RepositoriesByOwner.default_branch
    listed = checkout.git.run("ls-remote", RemoteName.ORIGIN, branch)
    return BranchTip(branch, CommitHash(listed.split()[0]))


# %% running on the default branch


def test_a_test_failing_on_the_default_branch_proves_the_finding(
    checkout: ProjectCheckout,
) -> None:
    publish_package(checkout, ProofDataset.DOUBLING_WRONG)

    attempt = runner(checkout).attempt(finding_test(ProofDataset.DOUBLING_SHOWN_WRONG))

    assert (attempt.outcome, attempt.tip) == (
        ProofOutcome.FAILS,
        github_s_tip(checkout),
    )


def test_a_proof_carries_the_test_the_commit_and_pytest_s_failure(
    checkout: ProjectCheckout,
) -> None:
    publish_package(checkout, ProofDataset.DOUBLING_WRONG)
    test = finding_test(ProofDataset.DOUBLING_SHOWN_WRONG)

    proof = runner(checkout).attempt(test).proof()

    assert proof == Proof(test, github_s_tip(checkout), "assert 6 == 4")


def test_a_test_passing_on_the_default_branch_proves_nothing(
    checkout: ProjectCheckout,
) -> None:
    publish_package(checkout, ProofDataset.DOUBLING_CORRECT)

    attempt = runner(checkout).attempt(finding_test(ProofDataset.DOUBLING_SHOWN_WRONG))

    assert attempt.outcome is ProofOutcome.PASSES
    with pytest.raises(PassingTestError):
        attempt.proof()


def test_a_bug_only_on_the_work_branch_proves_nothing(
    checkout: ProjectCheckout, monkeypatch: pytest.MonkeyPatch
) -> None:
    publish_package(checkout, ProofDataset.DOUBLING_CORRECT)
    checkout.git.run("switch", "--quiet", "--create", "work")
    commit_package(checkout, ProofDataset.DOUBLING_WRONG)
    monkeypatch.setenv(
        PythonVariable.MODULE_SEARCH_PATH,
        str(checkout.root / PythonProjectFile.SOURCE_DIRECTORY),
    )

    attempt = runner(checkout).attempt(finding_test(ProofDataset.DOUBLING_SHOWN_WRONG))

    assert attempt.outcome is ProofOutcome.PASSES


def test_github_s_default_branch_is_fetched_before_the_test_runs(
    checkout: ProjectCheckout, repositories: RepositoriesByOwner, owned_url: str
) -> None:
    publish_package(checkout, ProofDataset.DOUBLING_CORRECT)
    publish_package(
        repositories.clone(owned_url, "elsewhere"), ProofDataset.DOUBLING_WRONG
    )

    attempt = runner(checkout).attempt(finding_test(ProofDataset.DOUBLING_SHOWN_WRONG))

    assert (attempt.outcome, attempt.tip) == (
        ProofOutcome.FAILS,
        github_s_tip(checkout),
    )


def test_the_checkout_s_files_are_left_alone(checkout: ProjectCheckout) -> None:
    publish_package(checkout, ProofDataset.DOUBLING_WRONG)
    before = checkout.git.run("status", "--porcelain")

    runner(checkout).attempt(finding_test(ProofDataset.DOUBLING_SHOWN_WRONG))

    assert checkout.git.run("status", "--porcelain") == before


# %% broken tests


@pytest.mark.parametrize(
    "source",
    [
        ProofDataset.MISSPELT_IMPORT,
        ProofDataset.UNCOLLECTABLE_MODULE,
        ProofDataset.NO_TESTS,
        ProofDataset.READS_MISSING_DATA,
    ],
)
def test_a_broken_test_proves_nothing(
    checkout: ProjectCheckout, source: ProofDataset
) -> None:
    publish_package(checkout, ProofDataset.DOUBLING_WRONG)

    attempt = runner(checkout).attempt(finding_test(source))

    assert attempt.outcome is ProofOutcome.BROKEN
    with pytest.raises(BrokenTestError):
        attempt.proof()


def test_a_file_missing_outside_the_tests_still_proves_the_finding(
    checkout: ProjectCheckout,
) -> None:
    publish_package(checkout, ProofDataset.DOUBLING_WRONG)

    attempt = runner(checkout).attempt(finding_test(ProofDataset.CODE_MISSES_A_FILE))

    assert attempt.outcome is ProofOutcome.FAILS


def test_a_module_that_cannot_be_collected_is_reported_with_its_exception(
    checkout: ProjectCheckout,
) -> None:
    publish_package(checkout, ProofDataset.DOUBLING_WRONG)

    attempt = runner(checkout).attempt(finding_test(ProofDataset.UNCOLLECTABLE_MODULE))

    assert "No module named 'doublings'" in attempt.message


def test_an_interpreter_that_cannot_run_pytest_proves_nothing(
    checkout: ProjectCheckout, tmp_path: Path
) -> None:
    publish_package(checkout, ProofDataset.DOUBLING_WRONG)
    missing = str(tmp_path / "no-interpreter-here")

    attempt = runner(checkout, missing).attempt(
        finding_test(ProofDataset.DOUBLING_SHOWN_WRONG)
    )

    assert attempt.outcome is ProofOutcome.BROKEN


# %% a uv workspace


def commit_workspace_member(checkout: ProjectCheckout, package: ProofDataset) -> None:
    """
    Commit a version of the doubling package on the checked-out branch, as a member of
    a uv workspace.

    :param checkout: The checkout.
    :param package: The version.
    """
    member = checkout.root / DoublingProjectFile.WORKSPACE_MEMBER
    target = member / DoublingProjectFile.PACKAGE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(package.read_text())
    (checkout.root / PythonProjectFile.PYPROJECT).write_text(
        ProofDataset.WORKSPACE_PYPROJECT.read_text()
    )
    checkout.git.run("add", ".")
    checkout.git.run("commit", "--quiet", "--message", "Doubling, in a workspace")


def test_a_workspace_member_is_imported_from_the_default_branch(
    checkout: ProjectCheckout, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Not from the working checkout the interpreter installed it from, which holds the
    fix.
    """
    commit_workspace_member(checkout, ProofDataset.DOUBLING_WRONG)
    checkout.git.run(
        "push", "--quiet", RemoteName.ORIGIN, RepositoriesByOwner.default_branch
    )
    checkout.git.run("switch", "--quiet", "--create", "fix")
    commit_workspace_member(checkout, ProofDataset.DOUBLING_CORRECT)
    installed = checkout.root / DoublingProjectFile.WORKSPACE_MEMBER
    monkeypatch.setenv(
        PythonVariable.MODULE_SEARCH_PATH,
        str(installed / PythonProjectFile.SOURCE_DIRECTORY),
    )

    attempt = runner(checkout).attempt(finding_test(ProofDataset.DOUBLING_SHOWN_WRONG))

    assert attempt.outcome is ProofOutcome.FAILS


def workspace(root: Path, *members: Path) -> None:
    """
    Lay out a uv workspace whose members are under ``packages``.

    :param root: Its root.
    :param members: The directories made, relative to it.
    """
    (root / PythonProjectFile.PYPROJECT).write_text(
        ProofDataset.WORKSPACE_PYPROJECT.read_text()
    )
    for member in members:
        (root / member).mkdir(parents=True)


# %% the test file


def test_a_test_file_is_read_at_its_path_in_the_repository(
    checkout: ProjectCheckout,
) -> None:
    file = checkout.root / DoublingProjectFile.TEST
    file.parent.mkdir(parents=True)
    file.write_text(ProofDataset.DOUBLING_SHOWN_WRONG.read_text())

    assert FindingTest.read(checkout, file) == finding_test(
        ProofDataset.DOUBLING_SHOWN_WRONG
    )


def test_a_test_file_outside_the_checkout_is_refused(
    checkout: ProjectCheckout, tmp_path: Path
) -> None:
    with pytest.raises(FileOutsideCheckoutError):
        FindingTest.read(checkout, ProofDataset.DOUBLING_SHOWN_WRONG)


# %% the comment


def proof_of(source: str, commit: str = "0123456789abcdef") -> Proof:
    """:param source: The test's text.
    :param commit: The commit it failed on.
    :return: A proof by that test."""
    return Proof(
        FindingTest(DoublingProjectFile.TEST, source),
        BranchTip(RepositoriesByOwner.default_branch, CommitHash(commit)),
        "assert 6 == 4",
    )


def test_a_posted_proof_reads_back_as_it_was(settings: WorkflowSettings) -> None:
    proof = proof_of(ProofDataset.DOUBLING_SHOWN_WRONG.read_text())

    posted = [IssueComment(settings.owner, proof.comment())]

    assert Proof.posted_in(posted, [settings.owner]) == proof


def test_a_test_holding_comment_ends_and_fences_reads_back_as_it_was(
    settings: WorkflowSettings,
) -> None:
    proof = proof_of(ProofDataset.COMMENT_ENDS_AND_FENCES.read_text())

    posted = [IssueComment(settings.owner, proof.comment())]

    assert Proof.posted_in(posted, [settings.owner]) == proof


def test_the_latest_proof_counts(settings: WorkflowSettings) -> None:
    earlier = proof_of(ProofDataset.DOUBLING_SHOWN_WRONG.read_text(), "1111111")
    later = proof_of(ProofDataset.MISSPELT_IMPORT.read_text(), "2222222")

    posted = [
        IssueComment(settings.owner, earlier.comment()),
        IssueComment(settings.owner, later.comment()),
        IssueComment(settings.owner, "Looks right."),
    ]

    assert Proof.posted_in(posted, [settings.owner]) == later


def test_a_proof_by_an_untrusted_author_is_ignored(settings: WorkflowSettings) -> None:
    trusted = proof_of(ProofDataset.DOUBLING_SHOWN_WRONG.read_text(), "1111111")
    forged = proof_of(ProofDataset.MISSPELT_IMPORT.read_text(), "2222222")

    posted = [
        IssueComment(settings.owner.upper(), trusted.comment()),
        IssueComment(RepositoriesByOwner.foreign_owner, forged.comment()),
    ]

    assert Proof.posted_in(posted, [settings.owner]) == trusted


def test_an_issue_without_a_proof_has_none(settings: WorkflowSettings) -> None:
    posted = [IssueComment(settings.owner, "Looks right.")]

    assert Proof.posted_in(posted, [settings.owner]) is None
