"""
Finding labels picked on GitHub, completed by an Actions workflow.

A stage or priority label replaces the others of its kind, so changing a finding by hand
takes one pick.

Usage: ``python -m github_workflow.label_events <event file>``, with the ``issues``
event GitHub hands the workflow.
"""

from __future__ import annotations

import argparse
import json
import shlex
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from basstler_domain_model.github.repository_client import GitHubRepository
from basstler_domain_model.github.vocabulary import (
    IssueState,
    IssueStateReason,
    JSONModel,
    RestJSONKey,
)
from basstler_domain_model.repository import Repository

from github_workflow.findings import (
    FindingLabelling,
    FindingPrioritization,
    FindingStage,
    Priority,
)
from github_workflow.install import Requirement
from github_workflow.locations import ProjectFile, WorkflowTemplate
from github_workflow.work import WorkflowStep

# %% the event


class IssueEventKey(StrEnum):
    """
    The keys of an ``issues`` event that the REST answers do not share.
    """

    ISSUE = "issue"
    """
    The issue the event is about.
    """

    LABEL = "label"
    """
    The label just added.
    """

    REPOSITORY = "repository"
    """
    The repository the issue is in.
    """

    FULL_NAME = "full_name"
    """
    A repository's ``owner/name``.
    """


@dataclass(frozen=True)
class IssueLabelled(JSONModel):
    """
    A label added to an issue, as the ``issues`` event of type ``labeled`` reports it.
    """

    repository: Repository
    """
    The repository the issue is in.
    """

    number: int
    """
    The issue's number.
    """

    label: str
    """
    The name of the label added.
    """

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> IssueLabelled:
        return cls(
            Repository.parse(data[IssueEventKey.REPOSITORY][IssueEventKey.FULL_NAME]),
            data[IssueEventKey.ISSUE][RestJSONKey.NUMBER],
            data[IssueEventKey.LABEL][RestJSONKey.NAME],
        )


# %% completing the label


@dataclass(frozen=True)
class FindingLabelCompletion(FindingLabelling):
    """
    A label just added to an issue, completed: a priority as :class:`FindingPrioritization`
    gives it, a stage replacing the other stages, and an incorrect finding closed as not
    planned. A label removed again since, or one outside the findings, changes nothing.
    """

    number: int
    """
    The issue.
    """

    label: str
    """
    The name of the label added.
    """

    def run(self) -> str:
        issue = self.board.issue(self.number)
        if self.label not in issue.labels:
            return f"#{self.number} no longer carries {self.label}"
        if self.label in Priority:
            return FindingPrioritization(
                self.board, self.labels, self.number, Priority(self.label)
            ).run()
        if self.label not in FindingStage:
            return f"{self.label} is no finding label"
        stage = FindingStage(self.label)
        self.relabel(issue, [stage])
        if stage is FindingStage.INCORRECT and issue.state is IssueState.OPEN:
            self.board.close_issue(self.number, IssueStateReason.NOT_PLANNED)
        return f"moved #{self.number} to {stage}"


# %% the Actions workflow


class ActionRequirement(StrEnum):
    """
    What the Actions workflow installs to run the completion.
    """

    DOMAIN_MODEL = Requirement.DOMAIN_MODEL.value
    """
    The shared GitHub and git model, which no index serves.
    """

    WORKFLOW = "github-workflow @ git+https://github.com/LucaKro/GitHubWorkflow@main"
    """
    This package, from its default branch.
    """


class LabelCompletionPlaceholder(StrEnum):
    """
    The names the label completion workflow template leaves to be filled in.
    """

    REQUIREMENTS = "__REQUIREMENTS__"
    """
    What ``pip`` installs.
    """

    ENTRY_POINT = "__ENTRY_POINT__"
    """
    The command completing the label, before the event file.
    """


@dataclass(frozen=True)
class FindingAutomation(WorkflowStep):
    """
    The Actions workflow completing finding labels picked on GitHub, written into a
    checkout, to reach its default branch through a pull request.
    """

    root: Path
    """
    The checkout's root.
    """

    def run(self) -> str:
        workflow = (
            WorkflowTemplate.LABEL_COMPLETION_WORKFLOW.value.read_text()
            .replace(
                LabelCompletionPlaceholder.REQUIREMENTS,
                shlex.join(list(ActionRequirement)),
            )
            .replace(LabelCompletionPlaceholder.ENTRY_POINT, f"python -m {__name__}")
        )
        path = self.root / ProjectFile.LABEL_COMPLETION_WORKFLOW.value
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(workflow)
        return (
            f"wrote {ProjectFile.LABEL_COMPLETION_WORKFLOW.value}; commit it on a work "
            f"branch and open a draft, GitHub runs it once it is on the default branch"
        )


# %% entry point


def main() -> None:
    """
    Complete the label the event file on the command line reports added.
    """
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("event", type=Path, help="the issues event GitHub handed over")
    event = IssueLabelled.from_json(json.loads(parser.parse_args().event.read_text()))
    github = GitHubRepository.from_environment(event.repository)
    print(FindingLabelCompletion(github, github, event.number, event.label).run())


if __name__ == "__main__":
    main()
