"""
Save the notes block of this checkout's ``CLAUDE.local.md`` to the notes branch.

Usage: ``python -m github_workflow.notes save``
"""

from __future__ import annotations

import argparse
from pathlib import Path

from github_workflow.checkout import ProjectCheckout
from github_workflow.notes.branch import NotesBranch
from github_workflow.notes.saving import NotesCommand, NotesSave
from github_workflow.remotes import OwnedRemotes
from github_workflow.settings import WorkflowSettings

# %% entry point


def main() -> None:
    """
    Save the block and say what was saved.
    """
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("command", choices=list(NotesCommand))
    parser.parse_args()
    settings = WorkflowSettings()
    checkout = ProjectCheckout.containing(Path.cwd())
    remote = OwnedRemotes.read(checkout.git, settings).chosen
    saved = NotesSave(checkout, NotesBranch(checkout.git, remote, settings)).run()
    target = f"{remote.repository.full_name}, branch {settings.notes_branch}"
    if not saved:
        print(f"github-workflow: nothing changed since the last save to {target}")
        return
    print(f"github-workflow: saved {', '.join(map(str, saved))} to {target}")


if __name__ == "__main__":
    main()
