"""
Tests for :mod:`github_workflow.notes.unsaved`: notes edited since they were loaded or
last saved are saved without being asked, and nothing else is written.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from basstler_domain_model.claude_code.hooks import HookKey, HookValue
from basstler_domain_model.environment import ClaudeCodeVariable, PythonVariable
from basstler_domain_model.locations import PathEnumeration

from github_workflow.checkout import ProjectCheckout
from github_workflow.environment import WorkflowVariable
from github_workflow.locations import NotesFile
from github_workflow.notes.document import NotesBlock, NotesSection
from github_workflow.notes.unsaved import UnsavedNotes
from github_workflow.session_start import SessionStart
from github_workflow.settings import WorkflowSettings

from .repositories_by_owner import RepositoriesByOwner
from .test_notes_saving import edit, notes_of

# %% the plugin


class PluginFile(PathEnumeration):
    """
    The plugin's files these tests read.
    """

    HOOK_CONFIGURATION = Path(__file__).parents[1] / "hooks" / "hooks.json"
    """
    Which hook the plugin runs for which event.
    """

    NOTES_SAVE_HOOK = Path(__file__).parents[1] / "hooks" / "notes-save.sh"
    """
    The hook saving unsaved notes.
    """


def run_hook(checkout: ProjectCheckout) -> subprocess.CompletedProcess[str]:
    """
    :param checkout: The checkout the session works in.
    :return: The finished hook, run with this interpreter.
    """
    return subprocess.run(
        [str(PluginFile.NOTES_SAVE_HOOK.value)],
        input="{}",
        capture_output=True,
        text=True,
        env={
            **os.environ,
            WorkflowVariable.PYTHON: sys.executable,
            ClaudeCodeVariable.PROJECT_DIRECTORY: str(checkout.root),
        },
    )


# %% saving


def test_edited_notes_are_saved(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
) -> None:
    checkout = repositories.clone(owned_url, "session")
    SessionStart(checkout, settings).load_notes()
    edit(checkout, NotesSection.STANDING_NOTES, "a note")

    UnsavedNotes(checkout, settings).save()

    notes = notes_of(checkout, settings)
    assert notes.read(NotesFile.STANDING_NOTES) == "a note\n"


def test_saved_notes_are_no_longer_unsaved(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
) -> None:
    checkout = repositories.clone(owned_url, "session")
    SessionStart(checkout, settings).load_notes()
    edit(checkout, NotesSection.STANDING_NOTES, "a note")
    UnsavedNotes(checkout, settings).save()

    assert UnsavedNotes(checkout, settings).save() is None


def test_notes_without_edits_are_left_alone(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
) -> None:
    checkout = repositories.clone(owned_url, "session")
    SessionStart(checkout, settings).load_notes()

    assert UnsavedNotes(checkout, settings).save() is None


def test_a_checkout_without_notes_is_left_alone(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
) -> None:
    checkout = repositories.clone(owned_url, "session")

    assert UnsavedNotes(checkout, settings).save() is None


# %% the hook


def test_the_notes_are_saved_at_the_end_of_every_turn_and_of_the_session() -> None:
    """
    A cloud session's container can be reclaimed without the session ending, so the end
    of a turn is the last moment sure to come.
    """
    configuration = json.loads(PluginFile.HOOK_CONFIGURATION.value.read_text())
    hook = str(PluginFile.NOTES_SAVE_HOOK.value.name)

    for event in (HookValue.STOP, HookValue.SESSION_END):
        [entry] = configuration[HookKey.HOOKS][event]
        [command] = entry[HookKey.HOOKS]
        assert hook in command[HookKey.COMMAND]


def test_the_hook_shows_the_person_what_it_saved(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
) -> None:
    checkout = repositories.clone(owned_url, "session")
    SessionStart(checkout, settings).load_notes()
    edit(checkout, NotesSection.STANDING_NOTES, "a note")

    finished = run_hook(checkout)

    assert finished.returncode == 0
    assert (
        str(NotesFile.STANDING_NOTES.value)
        in json.loads(finished.stdout)[HookKey.SYSTEM_MESSAGE]
    )


def test_a_failed_save_keeps_the_edits_and_ends_the_turn_normally(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
) -> None:
    """
    Without an owned remote the save fails; the turn must not, and the edits wait in
    ``CLAUDE.local.md`` for the next try.
    """
    checkout = repositories.clone(owned_url, "session")
    SessionStart(checkout, settings).load_notes()
    edit(checkout, NotesSection.STANDING_NOTES, "a note")
    checkout.git.run("remote", "remove", "origin")

    finished = run_hook(checkout)

    assert finished.returncode == 0
    assert HookKey.SYSTEM_MESSAGE in json.loads(finished.stdout)
    assert NotesBlock.holds_unsaved_edits(checkout.claude_local.read_text())


def test_a_hook_runs_the_plugin_s_own_code_over_an_older_runtime(
    repositories: RepositoriesByOwner,
    owned_url: str,
    settings: WorkflowSettings,
    tmp_path: Path,
) -> None:
    plugin = PluginFile.NOTES_SAVE_HOOK.value.parents[1]
    runtime = tmp_path / "home" / ".virtualenvs" / "githubworkflow-runtime" / "bin"
    runtime.mkdir(parents=True)
    older = runtime / "python"
    older.write_text(
        "#!/usr/bin/env bash\n"
        "# An older runtime: the newer modules only come from the plugin's source.\n"
        f'case ":${{PYTHONPATH:-}}:" in *":{plugin / "src"}:"*) exec "{sys.executable}" "$@" ;; esac\n'
        'echo "No module named github_workflow.notes.unsaved" >&2\n'
        "exit 1\n"
    )
    older.chmod(0o755)
    checkout = repositories.clone(owned_url, "session")
    SessionStart(checkout, settings).load_notes()
    edit(checkout, NotesSection.STANDING_NOTES, "a note")
    environment = {
        name: value
        for name, value in os.environ.items()
        if name not in {WorkflowVariable.PYTHON, PythonVariable.MODULE_SEARCH_PATH}
    }

    subprocess.run(
        [str(PluginFile.NOTES_SAVE_HOOK.value)],
        input="{}",
        capture_output=True,
        text=True,
        env={
            **environment,
            "HOME": str(tmp_path / "home"),
            "CLAUDE_PLUGIN_ROOT": str(plugin),
            ClaudeCodeVariable.PROJECT_DIRECTORY: str(checkout.root),
        },
    )

    assert notes_of(checkout, settings).read(NotesFile.STANDING_NOTES) == "a note\n"
