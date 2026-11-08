"""
Tests for :mod:`github_workflow.notes.branch`: the notes land on the owner's remote, on
the branch the settings name.

Writing itself is the domain model's ``StorageBranch``, tested there.
"""

from __future__ import annotations

from pathlib import Path

from github_workflow.locations import NotesFile
from github_workflow.notes.branch import NotesBranch
from github_workflow.remotes import OwnedRemotes
from github_workflow.settings import WorkflowSettings

from .repositories_by_owner import RepositoriesByOwner

# %% where the notes land


def test_notes_are_saved_to_the_settings_branch_on_the_owner_s_remote(
    repositories: RepositoriesByOwner,
    owned_url: str,
    foreign_url: str,
    settings: WorkflowSettings,
):
    checkout = repositories.clone(foreign_url, "upstream-clone")
    checkout.git.run("remote", "add", "fork", owned_url)
    notes = NotesBranch.from_settings(
        checkout.git, OwnedRemotes.read(checkout.git, settings).chosen, settings
    )

    notes.write({Path(NotesFile.STANDING_NOTES): "a standing note\n"}, "Save")

    assert settings.notes_branch in repositories.branches(owned_url)
    assert settings.notes_branch not in repositories.branches(foreign_url)


# %% queued files


def test_a_file_queued_later_sorts_after_one_queued_before() -> None:
    first = NotesBranch.queued_file_name()
    later = NotesBranch.queued_file_name()

    assert sorted([later, first]) == [first, later]
