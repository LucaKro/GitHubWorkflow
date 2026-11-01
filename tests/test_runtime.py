"""
Tests for :mod:`github_workflow.runtime`: reading where the runtime's packages came
from, noticing that their branch moved on, and switching the runtime over to a new
build.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from basstler_domain_model.git.commands import GitCommandRunner
from basstler_domain_model.locations import PathEnumeration

from github_workflow.command_line import WorkflowCommand
from github_workflow.exceptions import NotARuntimeError
from github_workflow.runtime import (
    InstallSource,
    Runtime,
    RuntimeDistribution,
    RuntimePackage,
    RuntimeRebuild,
    RuntimeSwitch,
)
from github_workflow.settings import WorkflowSettings

from .repositories_by_owner import RepositoriesByOwner

# %% the dataset


class RuntimeDataset(PathEnumeration):
    """
    Pip's records of where a package was installed from.
    """

    INSTALLED_FROM_GIT = (
        Path(__file__).parent / "dataset" / "runtime" / "installed_from_git.json"
    )
    """
    A package installed from a branch of a git repository.
    """

    INSTALLED_FROM_A_CHECKOUT = (
        Path(__file__).parent / "dataset" / "runtime" / "installed_from_a_checkout.json"
    )
    """
    A package installed editable from a checkout.
    """

    def record(self) -> dict[str, object]:
        """:return: The record, decoded."""
        return json.loads(self.value.read_text())


@pytest.fixture
def repository(repositories: RepositoriesByOwner, settings: WorkflowSettings) -> str:
    """:return: The URL of a repository standing in for a package's."""
    return repositories.create(settings.owner)


def tip_of(repositories: RepositoriesByOwner, url: str) -> str:
    """:param repositories: Where to clone.
    :param url: A repository.
    :return: The commit its default branch is at."""
    clone = repositories.clone(url, "inspector").git
    return clone.commit_at(f"origin/{RepositoriesByOwner.default_branch}")


def runtime_at(url: str, commit: str) -> Runtime:
    """:param url: The repository the package came from.
    :param commit: The commit installed.
    :return: A runtime holding that one package."""
    source = InstallSource(url, commit, RepositoriesByOwner.default_branch)
    return Runtime((RuntimePackage(RuntimeDistribution.WORKFLOW, source),))


# %% where a package came from


def test_a_package_installed_from_git_has_its_repository_commit_and_branch():
    record = RuntimeDataset.INSTALLED_FROM_GIT.record()

    source = InstallSource.from_json(record)

    assert source == InstallSource(
        record["url"],
        record["vcs_info"]["commit_id"],
        record["vcs_info"]["requested_revision"],
    )


def test_a_package_installed_from_a_checkout_has_no_source():
    assert (
        InstallSource.from_json(RuntimeDataset.INSTALLED_FROM_A_CHECKOUT.record())
        is None
    )


# %% noticing main moved on


def test_a_branch_s_tip_is_read_from_its_repository(
    repositories: RepositoriesByOwner, repository: str, tmp_path: Path
):
    source = InstallSource(repository, "0" * 40, RepositoriesByOwner.default_branch)

    assert source.latest_commit(GitCommandRunner(tmp_path)) == tip_of(
        repositories, repository
    )


def test_an_unreachable_repository_has_no_tip(tmp_path: Path):
    source = InstallSource(str(tmp_path / "missing.git"), "0" * 40, "main")

    assert source.latest_commit(GitCommandRunner(tmp_path)) is None


def test_a_runtime_behind_main_names_the_update_command(
    repository: str, tmp_path: Path
):
    notice = runtime_at(repository, "0" * 40).notice(GitCommandRunner(tmp_path))

    assert notice is not None
    assert WorkflowCommand.command_line(WorkflowCommand.UPDATE) in notice


def test_a_runtime_at_main_says_nothing(
    repositories: RepositoriesByOwner, repository: str, tmp_path: Path
):
    runtime = runtime_at(repository, tip_of(repositories, repository))

    assert runtime.notice(GitCommandRunner(tmp_path)) is None


# %% rebuilding


def test_a_checkout_s_interpreter_is_no_runtime_to_rebuild(tmp_path: Path):
    with pytest.raises(NotARuntimeError):
        RuntimeRebuild(Runtime(()), tmp_path / "runtime").run()


def test_a_runtime_at_main_is_not_rebuilt(
    repositories: RepositoriesByOwner, repository: str, tmp_path: Path
):
    location = tmp_path / "environments" / "runtime"
    location.mkdir(parents=True)
    runtime = runtime_at(repository, tip_of(repositories, repository))

    RuntimeRebuild(runtime, location).run()

    assert [path.name for path in location.parent.iterdir()] == [location.name]


# %% switching over


def test_the_first_switch_turns_the_runtime_into_a_link_to_the_build(tmp_path: Path):
    location = tmp_path / "runtime"
    location.mkdir()
    build = tmp_path / ".runtime-build"
    build.mkdir()

    RuntimeSwitch(location).to(build)

    assert location.resolve() == build.resolve()
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        ".runtime-build",
        "runtime",
    ]


def test_a_later_switch_moves_the_link_and_removes_the_build_before(tmp_path: Path):
    location = tmp_path / "runtime"
    first = tmp_path / ".runtime-first"
    second = tmp_path / ".runtime-second"
    first.mkdir()
    second.mkdir()
    location.symlink_to(first.name)

    RuntimeSwitch(location).to(second)

    assert location.resolve() == second.resolve()
    assert not first.exists()
