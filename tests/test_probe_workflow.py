"""
Tests for the branch deletion workflow the probe pushes.
"""

from __future__ import annotations

from github_workflow.probe.scenarios import BranchName, WorkflowPlaceholder

# %% filling in the template


def test_the_filled_workflow_leaves_no_placeholder():
    filled = WorkflowPlaceholder.filled_workflow(
        f"{BranchName.WORKFLOW}stamp", f"{BranchName.DELETED_BY_WORKFLOW}stamp"
    )

    assert not any(placeholder in filled for placeholder in WorkflowPlaceholder)


def test_the_filled_workflow_names_both_branches():
    workflow = f"{BranchName.WORKFLOW}stamp"
    deleted = f"{BranchName.DELETED_BY_WORKFLOW}stamp"

    filled = WorkflowPlaceholder.filled_workflow(workflow, deleted)

    assert workflow in filled and deleted in filled
