"""
Tests for :mod:`github_workflow.probe.publish`: a directory of results lands on the
results branch under its own name, and the checkout is left alone.
"""

from __future__ import annotations

from pathlib import Path

from basstler_domain_model.git.commands import RemoteBranch, RemoteName
from basstler_domain_model.git.storage_branch import StorageBranch

from github_workflow.probe.publish import ResultsBranch, ResultsPublication

from .repositories_by_owner import RepositoriesByOwner

# %% publishing


def test_results_land_on_the_results_branch_under_their_directory_s_name(
    repositories: RepositoriesByOwner, owned_url: str, tmp_path: Path
):
    checkout = repositories.clone(owned_url, "session")
    directory = tmp_path / "check-1"
    directory.mkdir()
    (directory / "report.md").write_text("all well\n")
    before = checkout.git.run("status", "--porcelain")

    ResultsPublication(checkout.git, directory).publish()

    reader = repositories.clone(owned_url, "reader").git
    results = StorageBranch(reader, RemoteBranch(RemoteName.ORIGIN, ResultsBranch.NAME))
    results.fetch()
    assert results.read(Path("check-1/report.md")) == "all well"
    assert checkout.git.run("status", "--porcelain") == before
