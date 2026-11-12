"""
Tests for :mod:`github_workflow.probe`: the probe writes only to a remote of the
owner's, whatever ``origin`` points at.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from domain_model.git.revisions import BranchName
from domain_model.git.storage_branch import StorageBranch
from domain_model.github.clients import GitHubApi

from github_workflow.exceptions import NoOwnedRemoteError
from github_workflow.probe import __main__ as probe_entry_point
from github_workflow.probe import publish
from github_workflow.probe.publish import ResultsBranch, ResultsPublication
from github_workflow.remotes import OwnedRemotes
from github_workflow.settings import WorkflowSettings

from .repositories_by_owner import RepositoriesByOwner

# %% a foreign origin


@pytest.fixture(autouse=True)
def unreachable_github(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Points every client the probe builds at an address nothing answers on, so no test
    reaches GitHub.
    """
    monkeypatch.setattr(
        GitHubApi, "from_environment", lambda: GitHubApi("token", "http://127.0.0.1:9")
    )


@pytest.mark.parametrize(
    "entry_point", [probe_entry_point.main, publish.main], ids=["probe", "publish"]
)
def test_a_foreign_origin_is_refused_before_anything_is_written(
    repositories: RepositoriesByOwner,
    foreign_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    entry_point: Callable[[], None],
) -> None:
    checkout = repositories.clone(foreign_url, "upstream-clone")
    output = tmp_path / "check-1"
    output.mkdir()
    (output / "report.md").write_text("all well\n")
    before = repositories.branches(foreign_url)
    monkeypatch.chdir(checkout.root)
    monkeypatch.setattr("sys.argv", ["probe", str(output)])

    with pytest.raises(NoOwnedRemoteError):
        entry_point()

    assert repositories.branches(foreign_url) == before


def test_results_go_to_the_owned_remote_when_origin_is_foreign(
    repositories: RepositoriesByOwner,
    foreign_url: str,
    owned_url: str,
    settings: WorkflowSettings,
    tmp_path: Path,
) -> None:
    checkout = repositories.clone(foreign_url, "upstream-clone")
    checkout.git.run("remote", "add", "fork", owned_url)
    directory = tmp_path / "check-1"
    directory.mkdir()
    (directory / "report.md").write_text("all well\n")
    before = repositories.branches(foreign_url)
    remote = OwnedRemotes.read(checkout.git, settings).chosen

    ResultsPublication(remote, directory).publish()

    results = StorageBranch(remote.branch(BranchName(ResultsBranch.NAME)))
    results.fetch()
    published = results.read(Path("check-1/report.md"))
    assert published == (directory / "report.md").read_text()
    assert repositories.branches(foreign_url) == before
