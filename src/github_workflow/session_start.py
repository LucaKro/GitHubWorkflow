"""
What a session starts with, answered to the Claude Code hook.

Writes the notes and this branch's progress into ``CLAUDE.local.md``, computes the
sections that read the owner's repository on GitHub, and checks the runtime; one line
per thing the session should know is shown to the person and given to the model. Writes
no file to a remote; turning on the repository features the workflow relies on is the
only change it makes on GitHub.

Usage: ``python -m github_workflow.session_start [<hook event>]``, the event being
``SessionStart`` unless named.
"""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from basstler_domain_model.commands import CommandRunner

import github_workflow.report as report
from github_workflow.checkout import ProjectCheckout
from github_workflow.findings import Priority
from github_workflow.hooks import HookValue, ReportLine, SessionStartReport, Tone
from github_workflow.locations import NotesFile
from github_workflow.notes.branch import NotesBranch
from github_workflow.notes.document import NotesBlock, NotesSection
from github_workflow.command_line import NotesSubcommand, WorkflowCommand
from github_workflow.remotes import OwnedRemotes
from github_workflow.report import SectionName
from github_workflow.environment import WorkflowVariable
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

    def report(self) -> list[ReportLine]:
        """
        Load the notes into ``CLAUDE.local.md``, compute the sections that read the
        owner's repository on GitHub, and check the runtime, all at once, since each
        mostly waits on GitHub.

        :return: One line per thing the session should know.
        """
        owned = OwnedRemotes.read(self.checkout.git, self.settings).problem is None
        sections = list(SectionName) if owned else []
        with ThreadPoolExecutor() as pool:
            notes = pool.submit(self.load_notes)
            computed = [pool.submit(self.section, name) for name in sections]
        installed = WorkflowVariable.INSTALLED.read()
        lines = [ReportLine(installed, Tone.NEWS)] if installed else []
        lines.append(notes.result())
        for section in computed:
            lines += section.result()
        return lines

    def section(
        self, name: SectionName, timeout_seconds: float = 30.0
    ) -> list[ReportLine]:
        """
        :param name: A section that reads the owner's repository on GitHub.
        :param timeout_seconds: How long the section may take before it is stopped.
        :return: Its lines, computed in a process of its own so a failure or a slow
            answer costs only this section, and then one red line saying so.
        """
        computed = CommandRunner(self.checkout.root).run(
            sys.executable,
            "-m",
            report.__name__,
            name,
            timeout_seconds=timeout_seconds,
        )
        if not computed.succeeded:
            return [
                ReportLine(
                    f"github-workflow: could not compute the {name} section: "
                    f"{computed.summary}",
                    Tone.PROBLEM,
                )
            ]
        return [ReportLine.from_json(line) for line in computed.output.splitlines()]

    def load_notes(self) -> ReportLine:
        """
        Write the notes and this branch's progress into ``CLAUDE.local.md``.

        :return: What was loaded, or why nothing was.
        """
        remotes = OwnedRemotes.read(self.checkout.git, self.settings)
        if remotes.problem is not None:
            return ReportLine(
                f"github-workflow: notes not loaded: {remotes.problem.error_message()}",
                Tone.NEWS,
            )
        local = self.checkout.claude_local
        if NotesBlock.holds_unsaved_edits(local.read_text() if local.exists() else ""):
            save = WorkflowCommand.command_line(
                WorkflowCommand.NOTES, NotesSubcommand.SAVE
            )
            return ReportLine(
                f"github-workflow: notes not reloaded: {local.name} holds edits not "
                f"saved yet, kept as they are; save them with `{save}`",
                Tone.ACTION,
            )
        remote = remotes.chosen
        git = self.checkout.git
        notes = NotesBranch.on(git, remote, self.settings)
        exists = notes.fetch()
        branch = git.checked_out_branch()
        sections = {
            NotesSection.STANDING_NOTES: (
                notes.read(NotesFile.STANDING_NOTES) or ""
            ).strip()
        }
        progress = notes.read(NotesFile.progress_of(branch)) if branch else None
        if branch:
            sections[NotesSection.BRANCH_PROGRESS] = (progress or "").strip()
        source = f"{remote.repository.full_name}, branch {self.settings.notes_branch}"
        block = NotesBlock(
            source,
            WorkflowCommand.command_line(WorkflowCommand.NOTES, NotesSubcommand.SAVE),
            WorkflowCommand.command_line(),
            Priority.guide(),
            branch,
            sections,
        )
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
        return ReportLine(
            f"github-workflow: notes from {source}{state}{progress_state}", Tone.NEWS
        )


# %% entry point


def main() -> None:
    """
    Print what the session starts with, as the hook's answer.
    """
    checkout = ProjectCheckout.around(Path.cwd())
    if checkout is None:
        lines = [
            ReportLine(
                "github-workflow: not in a git checkout, so no notes were loaded",
                Tone.NEWS,
            )
        ]
    else:
        lines = SessionStart(checkout, WorkflowSettings()).report()
    event = HookValue(sys.argv[1]) if sys.argv[1:] else HookValue.SESSION_START
    print(SessionStartReport(lines, event).json())


if __name__ == "__main__":
    main()
