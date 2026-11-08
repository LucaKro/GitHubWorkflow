"""
The repository features the workflow relies on - GitHub deleting merged branches,
issues, Actions and Discussions - each reported where it is off, with where to turn it
on. The workflow never turns one on: the person opts in.
"""

from __future__ import annotations

from dataclasses import dataclass

from basstler_domain_model.github.repository_client import (
    RepositoryFeatures,
)
from basstler_domain_model.github.vocabulary import WorkflowState
from basstler_domain_model.repository import Repository

from github_workflow.report_lines import ReportLine, Speaker, Tone
from github_workflow.report_section import ReportSection
from github_workflow.workflow_templates import NotesBranchWorkflow

# %% a feature left off


@dataclass(frozen=True)
class SwitchedOffFeature:
    """
    A feature the workflow relies on that a repository has turned off.
    """

    feature: str
    """
    The feature, as the line names it.
    """

    purpose: str
    """
    What the workflow needs it for.
    """

    setting: str
    """
    The setting that turns it on, as GitHub's page names it.
    """

    page: str
    """
    The page the setting is on.
    """

    def line(self, repository: Repository) -> ReportLine:
        """
        :param repository: The repository that has it off.
        :return: That it is off, and where the person turns it on.
        """
        return ReportLine(
            Speaker.WORKFLOW.says(
                f"{repository} has {self.feature} turned off; {self.purpose}. Ask the "
                f"person whether to turn on {self.setting} at {self.page}"
            ),
            Tone.ACTION,
        )


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

    features: RepositoryFeatures
    """
    Its settings, its Discussions and its Actions workflows, as GitHub has them.
    """

    def lines(self) -> list[ReportLine]:
        return [feature.line(self.repository) for feature in self.switched_off()]

    def switched_off(self) -> list[SwitchedOffFeature]:
        """
        :return: Each feature the workflow relies on that the repository has off.
        """
        settings = self.repository.settings_url
        off = []
        if not self.features.deletes_merged_branches():
            off.append(
                SwitchedOffFeature(
                    "GitHub's deletion of merged branches",
                    "with it on, a merged pull request's branch needs no cleanup",
                    '"Automatically delete head branches"',
                    settings,
                )
            )
        if not self.features.issues_enabled():
            off.append(
                SwitchedOffFeature(
                    "issues", "findings are filed as issues", '"Issues"', settings
                )
            )
        if self.features.actions_enabled() is False:
            off.append(
                SwitchedOffFeature(
                    "GitHub Actions",
                    "they run the workflows the notes branch carries, but once on, "
                    "they run every workflow on the repository, an upstream's on a "
                    "fork among them, under your account",
                    "Actions",
                    self.repository.actions_settings_url,
                )
            )
        notes_workflows = {
            str(workflow.destination) for workflow in NotesBranchWorkflow
        }
        stopped = [
            workflow
            for workflow in self.features.workflows()
            if workflow.path in notes_workflows
            and workflow.state not in (WorkflowState.ACTIVE, WorkflowState.DELETED)
        ]
        if stopped:
            named = ", ".join(
                f"{workflow.name} ({workflow.state})" for workflow in stopped
            )
            off.append(
                SwitchedOffFeature(
                    f"the notes branch's workflows {named}",
                    "they post ideas, delete branches and read upstream reviews",
                    "each workflow, or the workflows of a fork",
                    self.repository.actions_url,
                )
            )
        if not self.features.discussions_enabled():
            off.append(
                SwitchedOffFeature(
                    "Discussions",
                    "ideas and the session log, which records what sessions close "
                    "and delete on their own, are posted there",
                    '"Discussions"',
                    settings,
                )
            )
        return off
