"""
Write the notes and this branch's progress into ``CLAUDE.local.md`` at the start of a
session, and print one line saying what was loaded - and one more when the workflow's
runtime is behind main. Never writes to a remote.

Usage: ``python -m github_workflow.session_start``
"""

from __future__ import annotations

from pathlib import Path

from github_workflow.checkout import ProjectCheckout
from github_workflow.locations import NotesFile
from github_workflow.notes.branch import NotesBranch
from github_workflow.notes.document import NotesBlock, NotesSection
from github_workflow.command_line import NotesSubcommand, WorkflowCommand
from github_workflow.remotes import OwnedRemotes
from github_workflow.runtime import Runtime
from github_workflow.settings import WorkflowSettings

# %% entry point


def main() -> None:
    """
    Load the notes, or say in one line why they were not loaded.
    """
    settings = WorkflowSettings()
    checkout = ProjectCheckout.containing(Path.cwd())
    notice = Runtime.installed().notice(checkout.git)
    if notice is not None:
        print(notice)
    remotes = OwnedRemotes.read(checkout.git, settings)
    if remotes.problem is not None:
        print(f"github-workflow: notes not loaded: {remotes.problem.error_message()}")
        return
    remote = remotes.chosen
    notes = NotesBranch.on(checkout.git, remote, settings)
    exists = notes.fetch()
    branch = checkout.git.checked_out_branch()
    sections = {NotesSection.STANDING_NOTES: notes.read(NotesFile.STANDING_NOTES) or ""}
    progress = notes.read(NotesFile.progress_of(branch)) if branch else None
    if branch:
        sections[NotesSection.BRANCH_PROGRESS] = progress or ""
    source = f"{remote.repository.full_name}, branch {settings.notes_branch}"
    block = NotesBlock(
        source,
        WorkflowCommand.command_line(WorkflowCommand.NOTES, NotesSubcommand.SAVE),
        WorkflowCommand.command_line(),
        branch,
        sections,
    )
    existing = (
        checkout.claude_local.read_text() if checkout.claude_local.exists() else ""
    )
    checkout.claude_local.write_text(block.written_into(existing))
    checkout.exclude_claude_local()
    state = "" if exists else " (not created yet: the first save creates it)"
    progress_state = (
        f"; progress for {branch}: {'loaded' if progress else 'none yet'}"
        if branch
        else ""
    )
    print(f"github-workflow: notes from {source}{state}{progress_state}")


if __name__ == "__main__":
    main()
