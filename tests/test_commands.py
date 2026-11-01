"""
Tests for the two commands: the session start reads the notes into ``CLAUDE.local.md``
and never pushes, the save pushes them back, and neither writes to anyone else's
repository.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import github_workflow.notes
import github_workflow.session_start
from github_workflow.checkout import ProjectCheckout
from github_workflow.exceptions import NoOwnedRemoteError
from github_workflow.locations import GitFile, NotesFile, ProjectFile
from github_workflow.notes.branch import NotesBranch
from github_workflow.notes.document import NotesBlock, NotesSection
from github_workflow.notes.saving import NotesCommand
from github_workflow.remotes import OwnedRemotes
from github_workflow.settings import WorkflowSettings

from .repositories_by_owner import RepositoriesByOwner

# %% helpers


def run(
    module: str, checkout: ProjectCheckout, *arguments: str
) -> subprocess.CompletedProcess:
    """
    :param module: The command's module.
    :param checkout: The checkout to run it in.
    :param arguments: Its arguments.
    :return: The finished command.
    """
    return subprocess.run(
        [sys.executable, "-m", module, *arguments],
        cwd=checkout.root,
        capture_output=True,
        text=True,
    )


def start_session(checkout: ProjectCheckout) -> subprocess.CompletedProcess:
    """:param checkout: The checkout a session starts in.
    :return: The finished session start."""
    return run(github_workflow.session_start.__name__, checkout)


def save(checkout: ProjectCheckout) -> subprocess.CompletedProcess:
    """:param checkout: The checkout whose notes block is saved.
    :return: The finished save."""
    return run(github_workflow.notes.__name__, checkout, NotesCommand.SAVE)


def saved_notes(
    repositories: RepositoriesByOwner, url: str, settings: WorkflowSettings
) -> NotesBranch:
    """
    :param repositories: Where to make a fresh clone.
    :param url: The repository the notes live in.
    :param settings: The workflow's settings.
    :return: Its notes branch as a fresh clone sees it, fetched.
    """
    checkout = repositories.clone(url, "inspector")
    notes = NotesBranch(
        checkout.git, OwnedRemotes.read(checkout.git, settings).chosen, settings
    )
    notes.fetch()
    return notes


# %% session start


def test_a_session_starts_with_the_notes_and_this_branch_s_progress(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
):
    writer = repositories.clone(owned_url, "writer")
    NotesBranch(
        writer.git, OwnedRemotes.read(writer.git, settings).chosen, settings
    ).write(
        {
            Path(NotesFile.STANDING_NOTES): "a standing note\n",
            NotesFile.progress_of("feature"): "halfway there\n",
        },
        "Save",
    )
    checkout = repositories.clone(owned_url, "session")
    checkout.git.run("switch", "--quiet", "--create", "feature")

    start_session(checkout)

    sections = NotesBlock.read_sections(checkout.claude_local.read_text())
    assert sections[NotesSection.STANDING_NOTES] == "a standing note"
    assert sections[NotesSection.BRANCH_PROGRESS] == "halfway there"


def test_claude_local_md_is_excluded_from_git_once(
    repositories: RepositoriesByOwner, owned_url: str
):
    checkout = repositories.clone(owned_url, "session")

    start_session(checkout)
    start_session(checkout)

    exclude = checkout.root / checkout.git.run(
        "rev-parse", "--git-path", str(GitFile.EXCLUDE)
    )
    assert exclude.read_text().splitlines().count(str(ProjectFile.CLAUDE_LOCAL)) == 1


def test_a_session_start_pushes_nothing(
    repositories: RepositoriesByOwner, owned_url: str
):
    before = repositories.branches(owned_url)

    start_session(repositories.clone(owned_url, "session"))

    assert repositories.branches(owned_url) == before


def test_a_session_in_somebody_else_s_repository_loads_nothing(
    repositories: RepositoriesByOwner, foreign_url: str, settings: WorkflowSettings
):
    checkout = repositories.clone(foreign_url, "theirs")

    finished = start_session(checkout)

    refusal = NoOwnedRemoteError(settings.owner, ("origin",)).error_message()
    assert refusal in finished.stdout
    assert not checkout.claude_local.exists()


# %% saving


def test_an_edited_note_is_saved_to_the_notes_branch(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
):
    checkout = repositories.clone(owned_url, "session")
    start_session(checkout)
    document = checkout.claude_local.read_text()
    marker = NotesSection.STANDING_NOTES.start_marker
    checkout.claude_local.write_text(document.replace(marker, f"{marker}\na new note"))

    save(checkout)

    assert (
        saved_notes(repositories, owned_url, settings).read(NotesFile.STANDING_NOTES)
        == "a new note"
    )


def test_saving_without_changes_pushes_nothing(
    repositories: RepositoriesByOwner, owned_url: str
):
    checkout = repositories.clone(owned_url, "session")
    start_session(checkout)
    before = repositories.branches(owned_url)

    save(checkout)

    assert repositories.branches(owned_url) == before


def test_saving_in_somebody_else_s_repository_is_refused(
    repositories: RepositoriesByOwner, foreign_url: str
):
    checkout = repositories.clone(foreign_url, "theirs")
    checkout.claude_local.write_text(
        NotesBlock("", "", "", {NotesSection.STANDING_NOTES: "a note"}).render()
    )
    before = repositories.branches(foreign_url)

    finished = save(checkout)

    assert finished.returncode != 0
    assert repositories.branches(foreign_url) == before
