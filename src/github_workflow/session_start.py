"""
Write the notes and this branch's progress into ``CLAUDE.local.md`` at the start of a.

session, and answer the hook with one line saying what was loaded - and one more when
the workflow's runtime is behind main - shown to the person and given to the model.
Never writes to a remote.

Usage: ``python -m github_workflow.session_start``
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from github_workflow.checkout import ProjectCheckout
from github_workflow.hooks import SessionStartReport
from github_workflow.locations import NotesFile
from github_workflow.notes.branch import NotesBranch
from github_workflow.notes.document import NotesBlock, NotesSection
from github_workflow.command_line import NotesSubcommand, WorkflowCommand
from github_workflow.remotes import OwnedRemotes
from github_workflow.runtime import Runtime
from github_workflow.settings import WorkflowSettings

# %% the session start


@dataclass(frozen=True)
class SessionStart:
    """
    What a session in one checkout starts with.
    """

    checkout: ProjectCheckout
    """
    The checkout the session works in.
    """

    settings: WorkflowSettings
    """
    Whose repositories are written to, and where the notes live.
    """

    def report(self) -> list[str]:
        """
        Load the notes into ``CLAUDE.local.md``.

        :return: One line per thing the session should know.
        """
        lines = [self.load_notes()]
        notice = Runtime.installed().notice(self.checkout.git)
        if notice is not None:
            lines.append(notice)
        return lines

    def load_notes(self) -> str:
        """
        Write the notes and this branch's progress into ``CLAUDE.local.md``.

        :return: What was loaded, or why nothing was.
        """
        remotes = OwnedRemotes.read(self.checkout.git, self.settings)
        if remotes.problem is not None:
            return (
                f"github-workflow: notes not loaded: {remotes.problem.error_message()}"
            )
        remote = remotes.chosen
        git = self.checkout.git
        notes = NotesBranch.on(git, remote, self.settings)
        exists = notes.fetch()
        branch = git.checked_out_branch()
        sections = {
            NotesSection.STANDING_NOTES: notes.read(NotesFile.STANDING_NOTES) or ""
        }
        progress = notes.read(NotesFile.progress_of(branch)) if branch else None
        if branch:
            sections[NotesSection.BRANCH_PROGRESS] = progress or ""
        source = f"{remote.repository.full_name}, branch {self.settings.notes_branch}"
        block = NotesBlock(
            source,
            WorkflowCommand.command_line(WorkflowCommand.NOTES, NotesSubcommand.SAVE),
            WorkflowCommand.command_line(),
            branch,
            sections,
        )
        local = self.checkout.claude_local
        local.write_text(
            block.written_into(local.read_text() if local.exists() else "")
        )
        self.checkout.exclude_claude_local()
        state = "" if exists else " (not created yet: the first save creates it)"
        progress_state = (
            f"; progress for {branch}: {'loaded' if progress else 'none yet'}"
            if branch
            else ""
        )
        return f"github-workflow: notes from {source}{state}{progress_state}"


# %% entry point


def main() -> None:
    """
    Print what the session starts with, as the hook's answer.
    """
    checkout = ProjectCheckout.around(Path.cwd())
    if checkout is None:
        lines = ["github-workflow: not in a git checkout, so no notes were loaded"]
    else:
        lines = SessionStart(checkout, WorkflowSettings()).report()
    print(SessionStartReport(lines).json())


if __name__ == "__main__":
    main()
