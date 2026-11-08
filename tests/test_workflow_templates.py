"""
Tests for :mod:`github_workflow.workflow_templates`: templates are filled in one pass,
and each workflow on the notes branch carries the files it runs.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from domain_model.templates import Placeholder

from github_workflow.label_events import FindingAutomation
from github_workflow.locations import ProjectFile
from github_workflow.workflow_templates import (
    DeletionPlaceholder,
    NotesBranchPlaceholder,
    NotesBranchWorkflow,
)

# %% filling in


def test_a_value_naming_another_placeholder_is_kept_as_it_is() -> None:
    template = f"{NotesBranchPlaceholder.NOTES_BRANCH} {DeletionPlaceholder.LIST_FILE}"

    filled = Placeholder.fill(
        template,
        {
            NotesBranchPlaceholder.NOTES_BRANCH: DeletionPlaceholder.LIST_FILE,
            DeletionPlaceholder.LIST_FILE: "list.md",
        },
    )

    assert filled == f"{DeletionPlaceholder.LIST_FILE} list.md"


# %% the notes branch's workflows


@pytest.mark.parametrize("workflow", list(NotesBranchWorkflow))
def test_a_workflow_is_written_with_every_file_it_runs(
    workflow: NotesBranchWorkflow,
) -> None:
    files = workflow.files("notes", {})

    assert set(files) == {
        workflow.destination.value,
        *(companion.destination.value for companion in workflow.companions),
    }


@pytest.mark.parametrize("workflow", list(NotesBranchWorkflow))
def test_a_workflow_names_where_the_notes_branch_keeps_its_files(
    workflow: NotesBranchWorkflow,
) -> None:
    text = workflow.files("notes", {})[workflow.destination.value]

    assert all(str(companion.destination) in text for companion in workflow.companions)


# %% the repository's own workflow


def test_the_repository_s_label_completion_workflow_is_the_one_the_workflow_writes(
    tmp_path: Path,
) -> None:
    FindingAutomation(tmp_path).run()

    checked_in = Path(__file__).parents[1] / ProjectFile.LABEL_COMPLETION_WORKFLOW
    written = tmp_path / ProjectFile.LABEL_COMPLETION_WORKFLOW
    assert checked_in.read_text() == written.read_text()
