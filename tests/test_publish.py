"""
Tests for :mod:`github_workflow.probe.publish`: a directory of results lands on the
results branch under its own name, and the checkout is left alone.
"""

from __future__ import annotations

from pathlib import Path

from domain_model.git.commands import RemoteBranch, RemoteName
from domain_model.git.storage_branch import StorageBranch

from github_workflow.probe.publish import ResultsBranch, ResultsPublication
from github_workflow.remotes import OwnedRemotes
from github_workflow.settings import WorkflowSettings

from .repositories_by_owner import RepositoriesByOwner

# %% publishing


def test_results_land_on_the_results_branch_under_their_directory_s_name(
    repositories: RepositoriesByOwner,
    owned_url: str,
    settings: WorkflowSettings,
    tmp_path: Path,
) -> None:
    checkout = repositories.clone(owned_url, "session")
    directory = tmp_path / "check-1"
    directory.mkdir()
    (directory / "report.md").write_text("all well\n")
    before = checkout.git.run("status", "--porcelain")

    remote = OwnedRemotes.read(checkout.git, settings).chosen

    ResultsPublication(checkout.git, remote, directory).publish()

    reader = repositories.clone(owned_url, "reader").git
    results = StorageBranch(reader, RemoteBranch(RemoteName.ORIGIN, ResultsBranch.NAME))
    results.fetch()
    assert results.read(Path("check-1/report.md")) == "all well\n"
    assert checkout.git.run("status", "--porcelain") == before
