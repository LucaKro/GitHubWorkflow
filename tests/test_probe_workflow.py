"""
Tests for the branch deletion workflow the probe pushes.
"""

from __future__ import annotations

from github_workflow.locations import ProbeTemplate
from github_workflow.probe.scenarios import BranchName
from github_workflow.workflow_templates import TemplatePlaceholder

# %% filling in the template


def filled(workflow: str, deleted: str) -> str:
    """
    :param workflow: The branch the workflow is pushed on.
    :param deleted: The other branch it deletes.
    :return: The probe's branch deletion workflow, naming both.
    """
    return TemplatePlaceholder.fill(
        ProbeTemplate.BRANCH_DELETION_WORKFLOW.read_text(),
        {
            TemplatePlaceholder.WORKFLOW_BRANCH: workflow,
            TemplatePlaceholder.DELETED_BRANCH: deleted,
        },
    )


def test_the_filled_workflow_leaves_no_placeholder():
    workflow = filled(
        f"{BranchName.WORKFLOW}stamp", f"{BranchName.DELETED_BY_WORKFLOW}stamp"
    )

    assert [
        placeholder for placeholder in TemplatePlaceholder if placeholder in workflow
    ] == []


def test_the_filled_workflow_names_both_branches():
    workflow = f"{BranchName.WORKFLOW}stamp"
    deleted = f"{BranchName.DELETED_BY_WORKFLOW}stamp"

    text = filled(workflow, deleted)

    assert workflow in text and deleted in text
