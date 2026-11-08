"""
Run every probe check against the repository checked out in the current directory, write
what was found into the directory given as the only argument, and publish it to the
probe results branch.

Usage: ``python -m github_workflow.probe <output directory>``
"""

from __future__ import annotations

import sys
from pathlib import Path

from basstler_domain_model.git.commands import GitCommandRunner
from basstler_domain_model.github.clients import GitHubApi

from github_workflow.locations import ProbeFile
from github_workflow.probe.publish import ResultsPublication
from github_workflow.probe.results import EnvironmentFact, ProbeReport
from github_workflow.probe.scenarios import Probe
from github_workflow.remotes import OwnedRemotes
from github_workflow.settings import WorkflowSettings

# %% entry point


def main() -> None:
    """
    Run the checks in order, write the report and the results, and publish both.

    :raises NoOwnedRemoteError: If no remote is the owner's.
    :raises AmbiguousOwnedRemoteError: If several are, and none is ``origin``.
    """
    output = Path(sys.argv[1])
    git = GitCommandRunner(Path.cwd())
    remote = OwnedRemotes.read(git, WorkflowSettings()).chosen
    probe = Probe(
        git=git,
        github=GitHubApi.from_environment(),
        remote=remote,
        stamp=output.name,
        report=ProbeReport(Probe.describe_environment(git)),
    )
    default_branch = probe.default_branch()
    probe.report.environment[EnvironmentFact.REPOSITORY] = (
        probe.remote.repository.full_name
    )
    probe.report.environment[EnvironmentFact.DEFAULT_BRANCH] = str(default_branch)
    probe.check_library(git.commit_at("HEAD"))
    probe.check_notes_branch()
    probe.check_issue_board()
    if default_branch is not None:
        probe.check_pull_request(default_branch)
        probe.check_stack(default_branch)
    probe.check_signals()
    probe.check_repository_settings()
    probe.check_workflow_branch_deletion()
    (output / ProbeFile.REPORT).write_text(probe.report.markdown())
    (output / ProbeFile.RESULTS).write_text(probe.report.to_json())
    print(probe.report.markdown())
    print(ResultsPublication(git, remote, output).publish())


if __name__ == "__main__":
    main()
