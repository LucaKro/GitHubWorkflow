"""
Run every probe check against the repository checked out in the current directory, and
write what was found into the directory given as the only argument.

Usage: ``python -m github_workflow.probe <output directory>``
"""

from __future__ import annotations

import sys
from pathlib import Path

from basstler_domain_model.repository import Repository

from github_workflow.locations import ProbeFile
from github_workflow.probe.commands import CommandRunner
from github_workflow.probe.rest import RestCaller
from github_workflow.probe.results import ProbeReport
from github_workflow.probe.scenarios import Probe

# %% entry point


def main() -> None:
    """
    Run the checks in order, then write the report and the results.
    """
    output = Path(sys.argv[1])
    runner = CommandRunner(Path.cwd())
    probe = Probe(
        runner=runner,
        caller=RestCaller(runner),
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
    print(probe.report.markdown())


if __name__ == "__main__":
    main()
