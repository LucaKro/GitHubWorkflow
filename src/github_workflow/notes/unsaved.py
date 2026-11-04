"""
Saving notes edited since they were loaded or last saved, without being asked: run as a
Claude Code hook at the end of each turn and of the session, so edits outlive a cloud
session's container.

Usage: ``python -m github_workflow.notes.unsaved``; prints the hook's answer when it
saved, nothing otherwise.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from github_workflow.checkout import ProjectCheckout
from github_workflow.hooks import HookKey, ReportLine, Tone
from github_workflow.notes.branch import NotesBranch
from github_workflow.notes.document import NotesBlock
from github_workflow.notes.saving import NotesSave
from github_workflow.remotes import OwnedRemotes
from github_workflow.settings import WorkflowSettings

# %% unsaved notes


@dataclass(frozen=True)
class UnsavedNotes:
    """
    The notes block of one checkout's ``CLAUDE.local.md``, saved when it holds edits.
    """

    checkout: ProjectCheckout
    """
    The checkout whose notes are saved.
    """

    settings: WorkflowSettings
    """
    Whose repository the notes are saved to, and on which branch.
    """

    def save(self) -> ReportLine | None:
        """
        Save the block when it was edited since it was loaded or last saved.

        :return: What was saved, ``None`` when the block holds no edits.
        """
        local = self.checkout.claude_local
        document = local.read_text() if local.exists() else ""
        if not NotesBlock.holds_unsaved_edits(document):
            return None
        remote = OwnedRemotes.read(self.checkout.git, self.settings).chosen
        notes = NotesBranch.on(self.checkout.git, remote, self.settings)
        saved = NotesSave(self.checkout, notes).run()
        files = ", ".join(str(path) for path in saved) or "nothing new"
        return ReportLine(
            f"github-workflow: saved the edited notes to {notes.branch.name}: {files}",
            Tone.NEWS,
        )


# %% entry point


def main() -> None:
    """
    Save the notes of the checkout around the working directory, and print the hook's
    answer when anything was saved.
    """
    checkout = ProjectCheckout.around(Path.cwd())
    if checkout is None:
        return
    line = UnsavedNotes(checkout, WorkflowSettings()).save()
    if line is not None:
        print(json.dumps({HookKey.SYSTEM_MESSAGE: line.shown}))


if __name__ == "__main__":
    main()
