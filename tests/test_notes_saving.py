"""
Tests for :mod:`github_workflow.notes.saving` with the session start loading the block:

progress is saved for the branch it was loaded for, and edits not saved yet survive a
new session start.
"""

from __future__ import annotations

from github_workflow.checkout import ProjectCheckout
from github_workflow.report_lines import Tone
from github_workflow.locations import NotesFile
from github_workflow.notes.branch import NotesBranch
from github_workflow.notes.document import NotesBlock, NotesSection
from github_workflow.notes.saving import NotesSave
from github_workflow.remotes import OwnedRemotes
from github_workflow.session_start import SessionStart
from github_workflow.settings import WorkflowSettings

from .repositories_by_owner import RepositoriesByOwner

# %% helpers


def edit(checkout: ProjectCheckout, section: NotesSection, text: str) -> None:
    """
    Replace one section's text in the checkout's ``CLAUDE.local.md``, as a session
    editing it would.

    :param checkout: The checkout.
    :param section: The section edited.
    :param text: Its new text.
    """
    document = checkout.claude_local.read_text()
    before, _, rest = document.partition(f"{section.start_marker}\n")
    _, _, after = rest.partition(section.end_marker)
    checkout.claude_local.write_text(
        f"{before}{section.start_marker}\n{text}\n{section.end_marker}{after}"
    )


def notes_of(checkout: ProjectCheckout, settings: WorkflowSettings) -> NotesBranch:
    """
    :param checkout: A clone of the owner's repository.
    :param settings: The workflow's settings.
    :return: Its notes branch, fetched.
    """
    remote = OwnedRemotes.read(checkout.git, settings).chosen
    notes = NotesBranch.from_settings(checkout.git, remote, settings)
    notes.fetch()
    return notes


def loaded_section(checkout: ProjectCheckout, section: NotesSection) -> str:
    """
    :param checkout: A checkout whose block was loaded.
    :param section: A section.
    :return: Its text in ``CLAUDE.local.md``.
    """
    return NotesBlock.read_sections(checkout.claude_local.read_text())[section]


# %% switching branches


def test_progress_is_saved_for_the_branch_it_was_loaded_for(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
):
    checkout = repositories.clone(owned_url, "session")
    checkout.git.run("switch", "--quiet", "--create", "feature-a")
    SessionStart(checkout, settings).load_notes()
    edit(checkout, NotesSection.BRANCH_PROGRESS, "progress on a")
    checkout.git.run("switch", "--quiet", "--create", "feature-b")

    NotesSave(checkout, notes_of(checkout, settings)).run()

    notes = notes_of(checkout, settings)
    assert notes.read(NotesFile.progress_file("feature-a")) == "progress on a\n"
    assert notes.read(NotesFile.progress_file("feature-b")) is None


# %% edits not saved yet


def test_edits_not_saved_yet_survive_a_new_session_start(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
):
    checkout = repositories.clone(owned_url, "session")
    SessionStart(checkout, settings).load_notes()
    edit(checkout, NotesSection.STANDING_NOTES, "a note never saved")

    line = SessionStart(checkout, settings).load_notes()

    assert loaded_section(checkout, NotesSection.STANDING_NOTES) == "a note never saved"
    assert line.tone is Tone.ACTION


def test_saved_edits_let_a_new_session_start_load_what_others_saved_since(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
):
    checkout = repositories.clone(owned_url, "session")
    SessionStart(checkout, settings).load_notes()
    edit(checkout, NotesSection.STANDING_NOTES, "my note")
    NotesSave(checkout, notes_of(checkout, settings)).run()
    other = repositories.clone(owned_url, "other-session")
    SessionStart(other, settings).load_notes()
    edit(other, NotesSection.STANDING_NOTES, "their note")
    NotesSave(other, notes_of(other, settings)).run()

    SessionStart(checkout, settings).load_notes()

    assert loaded_section(checkout, NotesSection.STANDING_NOTES) == "their note"
