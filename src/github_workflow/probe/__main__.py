"""
Run every probe check against the repository checked out in the current directory,
write what was found into the directory given as the only argument, and publish it to
the probe results branch.

Usage: ``python -m github_workflow.probe <output directory>``
"""

from __future__ import annotations

import sys
from enum import StrEnum
from pathlib import Path

from basstler_domain_model.commands import CommandRunner
from basstler_domain_model.git.commands import GitCommandRunner
from basstler_domain_model.git.storage_branch import StorageBranch
from basstler_domain_model.github.clients import GitHubApi
from basstler_domain_model.repository import Repository

from github_workflow.locations import ProbeFile
from github_workflow.probe.results import ProbeReport
from github_workflow.probe.scenarios import Probe

# %% where results go


class ResultsBranch(StrEnum):
    """
    The branch probe results are published to, outside every code branch, and deleted
    once they have been read.
    """

    NAME = "github-workflow/probe-results"
    """
    The branch on the remote.
    """

    REFERENCE = "refs/github-workflow/probe-results"
    """
    Where a fetch of it is kept.
    """


# %% entry point


def main() -> None:
    """
    Run the checks in order, write the report and the results, and publish both.
    """
    output = Path(sys.argv[1])
    runner = CommandRunner(Path.cwd())
    probe = Probe(
        runner=runner,
        github=GitHubApi.from_environment(),
        repository=Repository.from_remote_url(
            runner.run("git", "remote", "get-url", "origin").output
        ),
        stamp=output.name,
        report=ProbeReport(Probe.describe_environment(runner)),
    )
    default_branch = probe.default_branch()
    probe.report.environment["repository"] = probe.repository.full_name
    probe.report.environment["default branch"] = str(default_branch)
    probe.check_library(runner.run("git", "rev-parse", "HEAD").output)
    probe.check_notes_branch()
    probe.check_issue_board()
    if default_branch is not None:
        probe.check_pull_request(default_branch)
    probe.check_signals()
    probe.check_repository_settings()
    probe.check_workflow_branch_deletion()
    (output / ProbeFile.REPORT).write_text(probe.report.markdown())
    (output / ProbeFile.RESULTS).write_text(probe.report.to_json())
    results = StorageBranch(
        GitCommandRunner(Path.cwd()),
        "origin",
        ResultsBranch.NAME,
        ResultsBranch.REFERENCE,
    )
    results.fetch()
    results.write(
        {
            Path(output.name) / file.name: (output / file).read_text()
            for file in (ProbeFile.REPORT, ProbeFile.RESULTS)
        },
        f"Record probe results {output.name}",
    )
    print(probe.report.markdown())
    print(f"published to {ResultsBranch.NAME}: {output.name}/")


if __name__ == "__main__":
    main()
