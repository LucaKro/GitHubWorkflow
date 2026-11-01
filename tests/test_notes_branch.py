"""
Tests for :mod:`github_workflow.notes.branch`: the notes branch is read and written
without checking it out.
"""

from __future__ import annotations

from pathlib import Path

from github_workflow.checkout import ProjectCheckout
from github_workflow.locations import NotesFile
from github_workflow.notes.branch import NotesBranch
from github_workflow.remotes import OwnedRemotes
from github_workflow.settings import WorkflowSettings

from .repositories_by_owner import RepositoriesByOwner

# %% helpers


def notes_of(checkout: ProjectCheckout, settings: WorkflowSettings) -> NotesBranch:
    """
    :param checkout: A clone of the owner's repository.
    :param settings: The workflow's settings.
    :return: Its notes branch.
    """
    remote = OwnedRemotes.read(checkout.git, settings).chosen
    return NotesBranch(checkout.git, remote, settings)


# %% reading and writing


def test_before_the_first_save_there_is_nothing_to_read(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
):
    notes = notes_of(repositories.clone(owned_url, "mine"), settings)

    assert notes.fetch() is False
    assert notes.read(NotesFile.STANDING_NOTES) is None


def test_the_first_save_creates_the_branch_with_the_file(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
):
    notes_of(repositories.clone(owned_url, "writer"), settings).write(
        {Path(NotesFile.STANDING_NOTES): "a standing note\n"}, "Save"
    )
    reader = notes_of(repositories.clone(owned_url, "reader"), settings)

    assert reader.fetch() is True
    assert reader.read(NotesFile.STANDING_NOTES) == "a standing note"


def test_a_save_leaves_the_files_it_does_not_write_alone(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
):
    notes = notes_of(repositories.clone(owned_url, "mine"), settings)
    notes.write({Path(NotesFile.STANDING_NOTES): "a standing note\n"}, "Save")

    notes.write({NotesFile.progress_of("feature"): "progress\n"}, "Save")

    assert notes.read(NotesFile.STANDING_NOTES) == "a standing note"
    assert notes.read(NotesFile.progress_of("feature")) == "progress"


def test_a_session_that_saves_after_another_keeps_both_saves(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
):
    """
    The later session fetched before the earlier one saved, so its first push is refused
    and it builds again on the new tip.
    """
    first = notes_of(repositories.clone(owned_url, "first"), settings)
    second = notes_of(repositories.clone(owned_url, "second"), settings)
    first.write({Path(NotesFile.STANDING_NOTES): "a standing note\n"}, "Save")
    second.fetch()
    first.write({NotesFile.progress_of("first-branch"): "first\n"}, "Save")

    second.write({NotesFile.progress_of("second-branch"): "second\n"}, "Save")

    assert second.read(NotesFile.progress_of("first-branch")) == "first"
    assert second.read(NotesFile.progress_of("second-branch")) == "second"
