"""
Tests for :mod:`github_workflow.proofs`: a finding's test runs on the default branch as
GitHub has it, proves the finding only when it fails for a reason other than being
broken, and is posted as a comment that reads back only from a trusted author.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from basstler_domain_model.git.commands import RemoteName
from basstler_domain_model.github.issue_models import IssueComment
from basstler_domain_model.locations import PathEnumeration

from github_workflow.checkout import ProjectCheckout
from github_workflow.environment import PythonVariable
from github_workflow.exceptions import (
    BrokenTestError,
    FileOutsideCheckoutError,
    PassingTestError,
)
from github_workflow.locations import ProjectFile
from github_workflow.proof_settings import ProofSettings
from github_workflow.proofs import (
    BranchTip,
    FindingTest,
    DefaultBranchProofRunner,
    Proof,
    ProofOutcome,
)
from github_workflow.settings import WorkflowSettings
from github_workflow.workspace import PackageDirectories

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

    SHOWN_WRONG_BY_ANOTHER_NAME = (
        Path(__file__).parent / "dataset" / "proofs" / "shown_wrong_by_another_name.py"
    )
    """
    A test failing on the wrong package, which pytest collects only when told to.
    """

    GENERATED_FACTOR_SHOWN_WRONG = (
        Path(__file__).parent / "dataset" / "proofs" / "generated_factor_shown_wrong.py"
    )
    """
    A test failing on the factor a setup script generates.
    """

    GENERATE_FACTOR = (
        Path(__file__).parent / "dataset" / "proofs" / "generate_factor.py"
    )
    """
    The setup script, generating the wrong factor.
    """

    PROOF_SETTINGS = (
        Path(__file__).parent / "dataset" / "proofs" / "proof_settings.toml"
    )
    """
    A ``pyproject.toml`` saying how the project's proofs run.
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

    PACKAGE = ProjectFile.SOURCE_DIRECTORY / "doubling" / "__init__.py"
    """
    The package.
    """

    TEST = Path("tests") / "test_doubling.py"
    """
    The finding's test.
    """

    SETUP_SCRIPT = Path("scripts") / "generate_factor.py"
    """
    The script generating a module git ignores.
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
    checkout: ProjectCheckout,
    python: str = sys.executable,
    settings: ProofSettings = ProofSettings(),
) -> DefaultBranchProofRunner:
    """
    :param checkout: The checkout.
    :param python: The interpreter the tests run with.
    :param settings: How the project's proofs run.
    :return: Runs tests on the checkout's default branch on GitHub.
    """
    return DefaultBranchProofRunner(
        checkout.git,
        RemoteName.ORIGIN,
        RepositoriesByOwner.default_branch,
        python,
        settings,
    )


def finding_test(source: ProofDataset) -> FindingTest:
    """:param source: The test's text.
    :return: The test, where the doubling project keeps it."""
    return FindingTest(DoublingProjectFile.TEST, source.read_text())


def github_s_tip(checkout: ProjectCheckout) -> BranchTip:
    """:param checkout: The checkout.
    :return: Where GitHub's default branch is."""
    branch = RepositoriesByOwner.default_branch
    return BranchTip(
        branch, checkout.git.run("ls-remote", RemoteName.ORIGIN, branch).split()[0]
    )


# %% running on the default branch


def test_a_test_failing_on_the_default_branch_proves_the_finding(
    checkout: ProjectCheckout,
):
    publish_package(checkout, ProofDataset.DOUBLING_WRONG)

    attempt = runner(checkout).attempt(finding_test(ProofDataset.DOUBLING_SHOWN_WRONG))

    assert (attempt.outcome, attempt.tip) == (
        ProofOutcome.FAILS,
        github_s_tip(checkout),
    )


def test_a_proof_carries_the_test_the_commit_and_pytest_s_failure(
    checkout: ProjectCheckout,
):
    publish_package(checkout, ProofDataset.DOUBLING_WRONG)
    test = finding_test(ProofDataset.DOUBLING_SHOWN_WRONG)

    proof = runner(checkout).attempt(test).proof()

    assert proof == Proof(test, github_s_tip(checkout), "assert 6 == 4")


def test_a_test_passing_on_the_default_branch_proves_nothing(
    checkout: ProjectCheckout,
):
    publish_package(checkout, ProofDataset.DOUBLING_CORRECT)

    attempt = runner(checkout).attempt(finding_test(ProofDataset.DOUBLING_SHOWN_WRONG))

    assert attempt.outcome is ProofOutcome.PASSES
    with pytest.raises(PassingTestError):
        attempt.proof()


def test_a_bug_only_on_the_work_branch_proves_nothing(
    checkout: ProjectCheckout, monkeypatch: pytest.MonkeyPatch
):
    publish_package(checkout, ProofDataset.DOUBLING_CORRECT)
    checkout.git.run("switch", "--quiet", "--create", "work")
    commit_package(checkout, ProofDataset.DOUBLING_WRONG)
    monkeypatch.setenv(
        PythonVariable.MODULE_SEARCH_PATH,
        str(checkout.root / ProjectFile.SOURCE_DIRECTORY),
    )

    attempt = runner(checkout).attempt(finding_test(ProofDataset.DOUBLING_SHOWN_WRONG))

    assert attempt.outcome is ProofOutcome.PASSES


def test_github_s_default_branch_is_fetched_before_the_test_runs(
    checkout: ProjectCheckout, repositories: RepositoriesByOwner, owned_url: str
):
    publish_package(checkout, ProofDataset.DOUBLING_CORRECT)
    publish_package(
        repositories.clone(owned_url, "elsewhere"), ProofDataset.DOUBLING_WRONG
    )

    attempt = runner(checkout).attempt(finding_test(ProofDataset.DOUBLING_SHOWN_WRONG))

    assert (attempt.outcome, attempt.tip) == (
        ProofOutcome.FAILS,
        github_s_tip(checkout),
    )


def test_the_checkout_s_files_are_left_alone(checkout: ProjectCheckout):
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
    ],
)
def test_a_broken_test_proves_nothing(checkout: ProjectCheckout, source: ProofDataset):
    publish_package(checkout, ProofDataset.DOUBLING_WRONG)

    attempt = runner(checkout).attempt(finding_test(source))

    assert attempt.outcome is ProofOutcome.BROKEN
    with pytest.raises(BrokenTestError):
        attempt.proof()


def test_a_module_that_cannot_be_collected_is_reported_with_its_exception(
    checkout: ProjectCheckout,
):
    publish_package(checkout, ProofDataset.DOUBLING_WRONG)

    attempt = runner(checkout).attempt(finding_test(ProofDataset.UNCOLLECTABLE_MODULE))

    assert "No module named 'doublings'" in attempt.message


def test_an_interpreter_that_cannot_run_pytest_proves_nothing(
    checkout: ProjectCheckout, tmp_path: Path
):
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
    (checkout.root / ProjectFile.PYPROJECT).write_text(
        ProofDataset.WORKSPACE_PYPROJECT.read_text()
    )
    checkout.git.run("add", ".")
    checkout.git.run("commit", "--quiet", "--message", "Doubling, in a workspace")


def test_a_workspace_member_is_imported_from_the_default_branch(
    checkout: ProjectCheckout, monkeypatch: pytest.MonkeyPatch
):
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
        PythonVariable.MODULE_SEARCH_PATH, str(installed / ProjectFile.SOURCE_DIRECTORY)
    )

    attempt = runner(checkout).attempt(finding_test(ProofDataset.DOUBLING_SHOWN_WRONG))

    assert attempt.outcome is ProofOutcome.FAILS


def workspace(root: Path, *members: Path) -> None:
    """
    Lay out a uv workspace whose members are under ``packages``.

    :param root: Its root.
    :param members: The directories made, relative to it.
    """
    (root / ProjectFile.PYPROJECT).write_text(
        ProofDataset.WORKSPACE_PYPROJECT.read_text()
    )
    for member in members:
        (root / member).mkdir(parents=True)


def test_a_workspace_member_s_source_directory_is_searched(tmp_path: Path):
    source = Path("packages") / "laid-out" / ProjectFile.SOURCE_DIRECTORY
    workspace(tmp_path, source, Path("packages") / "flat")

    assert PackageDirectories(tmp_path).search_path() == [
        str(tmp_path),
        str(tmp_path / "packages" / "flat"),
        str(tmp_path / source),
    ]


def test_a_directory_the_workspace_excludes_is_not_searched(tmp_path: Path):
    workspace(tmp_path, Path("packages") / "unused")

    assert PackageDirectories(tmp_path).search_path() == [str(tmp_path)]


def test_a_project_that_is_no_workspace_is_searched_in_its_source_directory(
    tmp_path: Path,
):
    (tmp_path / ProjectFile.SOURCE_DIRECTORY).mkdir()

    assert PackageDirectories(tmp_path).search_path() == [
        str(tmp_path / ProjectFile.SOURCE_DIRECTORY)
    ]


# %% the project's own setup


def publish_setup_script(checkout: ProjectCheckout) -> None:
    """
    Put the setup script generating the wrong factor on GitHub's default branch, with
    the doubling package.

    :param checkout: A checkout on the default branch.
    """
    script = checkout.root / DoublingProjectFile.SETUP_SCRIPT
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(ProofDataset.GENERATE_FACTOR.read_text())
    checkout.git.run("add", str(DoublingProjectFile.SETUP_SCRIPT))
    publish_package(checkout, ProofDataset.DOUBLING_CORRECT)


def test_the_project_s_pytest_options_are_given_to_pytest(checkout: ProjectCheckout):
    publish_package(checkout, ProofDataset.DOUBLING_WRONG)
    settings = ProofSettings(pytest_options=("-o", "python_functions=check_*"))

    attempt = runner(checkout, settings=settings).attempt(
        finding_test(ProofDataset.SHOWN_WRONG_BY_ANOTHER_NAME)
    )

    assert attempt.outcome is ProofOutcome.FAILS


def test_the_project_s_setup_runs_before_the_test(checkout: ProjectCheckout):
    publish_setup_script(checkout)
    settings = ProofSettings(setup=(str(DoublingProjectFile.SETUP_SCRIPT),))

    attempt = runner(checkout, settings=settings).attempt(
        finding_test(ProofDataset.GENERATED_FACTOR_SHOWN_WRONG)
    )

    assert (attempt.outcome, attempt.message) == (ProofOutcome.FAILS, "assert 3 == 2")


def test_a_failing_setup_leaves_the_test_broken(checkout: ProjectCheckout):
    publish_package(checkout, ProofDataset.DOUBLING_WRONG)
    settings = ProofSettings(setup=("scripts/missing.py",))

    attempt = runner(checkout, settings=settings).attempt(
        finding_test(ProofDataset.DOUBLING_SHOWN_WRONG)
    )

    assert attempt.outcome is ProofOutcome.BROKEN


def test_the_settings_are_read_from_the_project_s_pyproject(tmp_path: Path):
    (tmp_path / ProjectFile.PYPROJECT).write_text(
        ProofDataset.PROOF_SETTINGS.read_text()
    )

    assert ProofSettings.read(tmp_path) == ProofSettings(
        ("-o", "python_functions=check_*"), ("scripts/generate_factor.py --wrong",)
    )


def test_a_project_without_a_pyproject_has_no_settings(tmp_path: Path):
    assert ProofSettings.read(tmp_path) == ProofSettings()


# %% the test file


def test_a_test_file_is_read_at_its_path_in_the_repository(checkout: ProjectCheckout):
    file = checkout.root / DoublingProjectFile.TEST
    file.parent.mkdir(parents=True)
    file.write_text(ProofDataset.DOUBLING_SHOWN_WRONG.read_text())

    assert FindingTest.read(checkout, file) == finding_test(
        ProofDataset.DOUBLING_SHOWN_WRONG
    )


def test_a_test_file_outside_the_checkout_is_refused(
    checkout: ProjectCheckout, tmp_path: Path
):
    with pytest.raises(FileOutsideCheckoutError):
        FindingTest.read(checkout, ProofDataset.DOUBLING_SHOWN_WRONG)


# %% the comment


def proof_of(source: str, commit: str = "0123456789abcdef") -> Proof:
    """:param source: The test's text.
    :param commit: The commit it failed on.
    :return: A proof by that test."""
    return Proof(
        FindingTest(DoublingProjectFile.TEST, source),
        BranchTip(RepositoriesByOwner.default_branch, commit),
        "assert 6 == 4",
    )


def test_a_posted_proof_reads_back_as_it_was(settings: WorkflowSettings):
    proof = proof_of(ProofDataset.DOUBLING_SHOWN_WRONG.read_text())

    posted = [IssueComment(settings.owner, proof.comment())]

    assert Proof.posted_in(posted, [settings.owner]) == proof


def test_a_test_holding_comment_ends_and_fences_reads_back_as_it_was(
    settings: WorkflowSettings,
):
    proof = proof_of('text = """\n-->\n````\n"""\n')

    posted = [IssueComment(settings.owner, proof.comment())]

    assert Proof.posted_in(posted, [settings.owner]) == proof


def test_the_latest_proof_counts(settings: WorkflowSettings):
    earlier = proof_of("def test_one(): pass\n", "1111111")
    later = proof_of("def test_two(): pass\n", "2222222")

    posted = [
        IssueComment(settings.owner, earlier.comment()),
        IssueComment(settings.owner, later.comment()),
        IssueComment(settings.owner, "Looks right."),
    ]

    assert Proof.posted_in(posted, [settings.owner]) == later


def test_a_proof_by_an_untrusted_author_is_ignored(settings: WorkflowSettings):
    trusted = proof_of("def test_one(): pass\n", "1111111")
    forged = proof_of("def test_two(): pass\n", "2222222")

    posted = [
        IssueComment(settings.owner.upper(), trusted.comment()),
        IssueComment(RepositoriesByOwner.foreign_owner, forged.comment()),
    ]

    assert Proof.posted_in(posted, [settings.owner]) == trusted


def test_an_issue_without_a_proof_has_none(settings: WorkflowSettings):
    posted = [IssueComment(settings.owner, "Looks right.")]

    assert Proof.posted_in(posted, [settings.owner]) is None
