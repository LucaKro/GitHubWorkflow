"""
The workflow's README and the diagrams of its architecture it holds, drawn anew from the
workflow's source when run.

Usage: ``python -m github_workflow.architecture``.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from domain_model.architecture.diagrams import (
    ClassDiagram,
    Diagram,
    ImportDiagram,
    ModuleGroup,
)
from domain_model.architecture.readme import ArchitectureReadme
from domain_model.architecture.source import PythonPackage

from github_workflow import (
    __main__,
    approval,
    checkout,
    cleanup,
    coarse_guard,
    command_line,
    command_steps,
    discussions,
    environment,
    exceptions,
    findings,
    freshness,
    guard,
    install,
    label_events,
    labels,
    locations,
    markers,
    notes,
    own_pull_request,
    plugin,
    policy,
    probe,
    project_tooling,
    proofs,
    pull_request_overview,
    push_hook,
    remotes,
    report,
    report_lines,
    report_section,
    repository_setup,
    runtime_check,
    session,
    session_start,
    settings,
    upstream,
    upstream_reviews,
    work,
    workflow_templates,
)
from github_workflow.locations import PackageLocation

# %% the diagrams


class WorkflowDiagram(StrEnum):
    """
    The diagrams of the workflow's README, by the key marking each; every part but the
    overview has a class diagram of its own.
    """

    OVERVIEW = "overview"
    """
    The parts of the workflow, and which imports which.
    """

    COMMANDS = "commands"
    """
    The commands a session runs, their arguments, and what each builds from the session.
    """

    WORK = "work"
    """
    Branches, commits, pushes, drafts, sync and the cleanup of branches.
    """

    RULES = "rules"
    """
    The rules every write passes, and the guard judging every command a session runs.
    """

    FINDINGS = "findings"
    """
    Findings, their proofs and their labels.
    """

    PULL_REQUESTS = "pull requests"
    """
    The own pull request, forks, their upstream and following its reviews.
    """

    SESSION_START = "session start"
    """
    The report a session starts with.
    """

    RUNTIME = "runtime"
    """
    The runtime the plugin installs and the probe of what a cloud session can reach.
    """

    NOTES = "notes"
    """
    The notes branch, the Discussions posted through it and its Actions workflows.
    """

    SHARED = "shared"
    """
    The files, environment variables, errors and markers every part names.
    """


# %% the README


class WorkflowReadme(ArchitectureReadme):
    """
    The workflow's README.
    """

    @property
    def path(self) -> Path:
        return PackageLocation.README

    @property
    def package(self) -> PythonPackage:
        return PythonPackage(directory=PackageLocation.DIRECTORY)

    @property
    def parts(self) -> list[ModuleGroup]:
        """
        :return: The parts of the workflow, each a group of its modules.
        """
        modules_of_parts = {
            WorkflowDiagram.COMMANDS: [__main__, command_line, command_steps],
            WorkflowDiagram.WORK: [checkout, cleanup, labels, session, work],
            WorkflowDiagram.RULES: [
                approval,
                coarse_guard,
                guard,
                policy,
                push_hook,
                remotes,
                settings,
            ],
            WorkflowDiagram.FINDINGS: [findings, label_events, proofs],
            WorkflowDiagram.PULL_REQUESTS: [
                freshness,
                own_pull_request,
                upstream,
                upstream_reviews,
            ],
            WorkflowDiagram.SESSION_START: [
                project_tooling,
                pull_request_overview,
                report,
                report_lines,
                report_section,
                repository_setup,
                session_start,
            ],
            WorkflowDiagram.RUNTIME: [install, plugin, probe, runtime_check],
            WorkflowDiagram.NOTES: [discussions, notes, workflow_templates],
            WorkflowDiagram.SHARED: [environment, exceptions, locations, markers],
        }
        return [
            ModuleGroup.from_modules(title=part, modules=modules)
            for part, modules in modules_of_parts.items()
        ]

    @property
    def diagrams(self) -> list[Diagram]:
        overview = ImportDiagram(
            key=WorkflowDiagram.OVERVIEW,
            package_name=self.package.name,
            groups=tuple(self.parts),
        )
        class_diagrams = [
            ClassDiagram(
                key=part.title,
                modules=part,
                left_out_bases=self.left_out_bases,
            )
            for part in self.parts
        ]
        return [overview, *class_diagrams]


# %% running it

if __name__ == "__main__":
    WorkflowReadme().write()
