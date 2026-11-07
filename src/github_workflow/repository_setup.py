"""
The repository features the workflow relies on - GitHub deleting merged branches,
issues, Actions and Discussions - each reported where it is off, with where to turn it
on. The workflow never turns one on: the person opts in.
"""

from __future__ import annotations

from dataclasses import dataclass

from basstler_domain_model.github.repository_client import (
    RepositoryDiscussions,
    RepositorySettings,
    RepositoryWorkflows,
)
from basstler_domain_model.github.vocabulary import WorkflowState
from basstler_domain_model.repository import Repository

from github_workflow.hooks import ReportLine, Speaker, Tone
from github_workflow.report_section import ReportSection
from github_workflow.workflow_templates import NotesBranchWorkflow

# %% the features


@dataclass(frozen=True)
class RepositorySetup(ReportSection):
    """
    Merged-branch deletion, issues, Actions, the notes branch's workflows and
    Discussions on one repository, each reported when it is off.
    """

    repository: Repository
    """
    The repository.
    """

    settings: RepositorySettings
    """
    Reads its settings.
    """

    discussions: RepositoryDiscussions
    """
    Says whether it has Discussions turned on.
    """

    workflows: RepositoryWorkflows
    """
    Says whether GitHub runs each of its Actions workflows.
    """

    def lines(self) -> list[ReportLine]:
        lines = []
        if not self.settings.deletes_merged_branches():
            lines.append(
                self._left_off(
                    "GitHub's deletion of merged branches",
                    "with it on, a merged pull request's branch needs no cleanup",
                    '"Automatically delete head branches"',
                    self.repository.settings_url,
                )
            )
        if not self.settings.issues_enabled():
            lines.append(
                self._left_off(
                    "issues",
                    "findings are filed as issues",
                    '"Issues"',
                    self.repository.settings_url,
                )
            )
        if self.settings.actions_enabled() is False:
            lines.append(
                self._left_off(
                    "GitHub Actions",
                    "they run the workflows the notes branch carries, but once on, "
                    "they run every workflow on the repository, an upstream's on a "
                    "fork among them, under your account",
                    "Actions",
                    f"{self.repository.settings_url}/actions",
                )
            )
        notes_workflows = {
            str(workflow.destination) for workflow in NotesBranchWorkflow
        }
        off = [
            workflow
            for workflow in self.workflows.workflows()
            if workflow.path in notes_workflows
            and workflow.state not in (WorkflowState.ACTIVE, WorkflowState.DELETED)
        ]
        if off:
            named = ", ".join(f"{workflow.name} ({workflow.state})" for workflow in off)
            lines.append(
                self._left_off(
                    f"the notes branch's workflows {named}",
                    "they post ideas, delete branches and read upstream reviews",
                    "each workflow, or the workflows of a fork",
                    f"{self.repository.url}/actions",
                )
            )
        if not self.discussions.discussions_enabled():
            lines.append(
                self._left_off(
                    "Discussions",
                    "ideas and the session log, which records what sessions close "
                    "and delete on their own, are posted there",
                    '"Discussions"',
                    self.repository.settings_url,
                )
            )
        return lines

    def _left_off(
        self, feature: str, purpose: str, setting: str, page: str
    ) -> ReportLine:
        """
        :param feature: The feature, as the line names it.
        :param purpose: What the workflow needs it for.
        :param setting: The setting that turns it on, as GitHub's page names it.
        :param page: The page the setting is on.
        :return: That it is off, and where the person turns it on.
        """
        return ReportLine(
            Speaker.WORKFLOW.says(
                f"{self.repository} has {feature} turned off; {purpose}. Ask the "
                f"person whether to turn on {setting} at {page}"
            ),
            Tone.ACTION,
        )
