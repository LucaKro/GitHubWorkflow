"""
Tests for the two commands: the session start reads the notes into ``CLAUDE.local.md``
and never pushes, the save pushes them back, and neither writes to anyone else's
repository.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from http import HTTPStatus
from pathlib import Path

import pytest

from basstler_domain_model.environment import (
    GitHubActionsVariable,
    GitHubCredentialVariable,
)
from basstler_domain_model.github.replayed_api import RecordedAnswer, ReplayedApi
from basstler_domain_model.github.repository_client import PullRequestListState
from basstler_domain_model.github.routes import QueryParameter, RepositoryRoute
from basstler_domain_model.github.vocabulary import IssueState, RestJSONKey
from basstler_domain_model.locations import PathEnumeration
from basstler_domain_model.repository import Repository

import github_workflow
import github_workflow.session_start
from github_workflow.checkout import ProjectCheckout
from github_workflow.environment import WorkflowVariable
from github_workflow.exceptions import NoOwnedRemoteError
from github_workflow.findings import FindingStage
from github_workflow.hooks import HookKey, HookValue, Tone
from github_workflow.locations import GitFile, NotesFile, ProjectFile
from github_workflow.notes.branch import NotesBranch
from github_workflow.notes.document import NotesBlock, NotesSection
from github_workflow.command_line import NotesSubcommand, WorkflowCommand
from github_workflow.remotes import OwnedRemotes
from github_workflow.settings import WorkflowSettings

from .repositories_by_owner import RepositoriesByOwner

# %% datasets


class SessionDataset(PathEnumeration):
    """
    The stand-ins the session hook is run with.
    """

    INSTALLER_STILL_INSTALLING = (
        Path(__file__).parent / "dataset" / "session" / "installer_still_installing.py"
    )
    """
    An installer whose install, started in the background, still runs.
    """


# %% GitHub, replayed


@pytest.fixture(autouse=True)
def github(
    monkeypatch: pytest.MonkeyPatch, settings: WorkflowSettings
) -> Iterator[ReplayedApi]:
    """
    :return: GitHub as every command run here reaches it, answering that the owner's
        repository has everything the workflow relies on set up, no open pull request,
        nothing waiting on the person's review, no findings, and no pull request
        whose branch is left to delete.
    """
    with ReplayedApi() as api:
        api.answers[("GET", root_path(settings))] = setting(HTTPStatus.OK, True)
        api.answers[("GET", actions_path(settings))] = RecordedAnswer(
            HTTPStatus.OK, json.dumps({RestJSONKey.ENABLED: True})
        )
        route = RepositoryRoute(
            Repository(settings.owner, RepositoriesByOwner.repository_name)
        )
        for listed in (PullRequestListState.OPEN, PullRequestListState.ALL):
            pull_requests = route.listing(
                route.pull_requests, {QueryParameter.STATE: listed.query}
            )
            api.answers[("GET", f"/{pull_requests}")] = RecordedAnswer(
                HTTPStatus.OK, "[]"
            )
        api.answers[("GET", f"/{route.review_requests()}")] = RecordedAnswer(
            HTTPStatus.OK, json.dumps({RestJSONKey.TOTAL_COUNT: 0})
        )
        for stage in FindingStage:
            findings = route.listing(
                route.issues(),
                {QueryParameter.LABELS: stage, QueryParameter.STATE: IssueState.OPEN},
            )
            api.answers[("GET", f"/{findings}")] = RecordedAnswer(HTTPStatus.OK, "[]")
        monkeypatch.setenv(GitHubActionsVariable.API_URL, api.url)
        monkeypatch.setenv(GitHubCredentialVariable.GH_TOKEN, "a-token")
        yield api


def actions_path(settings: WorkflowSettings) -> str:
    """:param settings: The workflow's settings.
    :return: The REST path of the owner's scratch repository's Actions permissions."""
    repository = Repository(settings.owner, RepositoriesByOwner.repository_name)
    return f"/{RepositoryRoute(repository).actions_permissions}"


def root_path(settings: WorkflowSettings) -> str:
    """:param settings: The workflow's settings.
    :return: The REST path of the owner's scratch repository."""
    repository = Repository(settings.owner, RepositoriesByOwner.repository_name)
    return f"/{RepositoryRoute(repository).root}"


def setting(status: HTTPStatus, deletes: bool) -> RecordedAnswer:
    """:param status: The status to answer with.
    :param deletes: Whether merged branches are deleted.
    :return: An answer carrying the merged-branch deletion setting."""
    return RecordedAnswer(
        status,
        json.dumps(
            {
                RestJSONKey.DELETE_BRANCH_ON_MERGE: deletes,
                RestJSONKey.HAS_ISSUES: True,
                RestJSONKey.DEFAULT_BRANCH: RepositoriesByOwner.default_branch,
            }
        ),
    )


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
    return run(
        github_workflow.__name__, checkout, WorkflowCommand.NOTES, NotesSubcommand.SAVE
    )


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
    notes = NotesBranch.on(
        checkout.git, OwnedRemotes.read(checkout.git, settings).chosen, settings
    )
    notes.fetch()
    return notes


# %% session start


def test_a_session_starts_with_the_notes_and_this_branch_s_progress(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
):
    writer = repositories.clone(owned_url, "writer")
    NotesBranch.on(
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


def test_a_session_start_is_shown_to_the_person_and_given_to_the_model(
    repositories: RepositoriesByOwner, owned_url: str
):
    finished = start_session(repositories.clone(owned_url, "session"))

    answer = json.loads(finished.stdout)
    given = answer[HookKey.HOOK_SPECIFIC_OUTPUT]
    assert given[HookKey.HOOK_EVENT_NAME] == HookValue.SESSION_START
    shown = answer[HookKey.SYSTEM_MESSAGE].splitlines()
    plain = given[HookKey.ADDITIONAL_CONTEXT].splitlines()
    assert [line for line in plain if any(line in seen for seen in shown)] == plain
    assert not [line for line in shown if line.startswith(f"\033[1;{Tone.PROBLEM}m")]


def test_a_session_outside_a_checkout_says_so_in_one_line(tmp_path: Path):
    finished = subprocess.run(
        [sys.executable, "-m", github_workflow.session_start.__name__],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    assert finished.returncode == 0
    assert len(json.loads(finished.stdout)[HookKey.SYSTEM_MESSAGE].splitlines()) == 1


def test_the_hook_answers_even_without_the_package(tmp_path: Path):
    finished = subprocess.run(
        [str(Path(__file__).parents[1] / "hooks" / "session-start.sh")],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={WorkflowVariable.PYTHON: str(tmp_path / "no-interpreter")},
    )

    assert finished.returncode == 0
    assert HookKey.SYSTEM_MESSAGE in json.loads(finished.stdout)


# %% a plugin that arrived late


def run_session_hook(
    checkout: ProjectCheckout,
    event: HookValue,
    session: str,
    markers: Path,
    installation: Path | None = None,
) -> subprocess.CompletedProcess:
    """
    :param checkout: The checkout the session works in.
    :param event: The hook event the hook runs for.
    :param session: The session's id.
    :param markers: Where the hook keeps which sessions it reported.
    :param installation: Holds the plugin the hook installs the runtime from and the
        home it installs it into; ``None`` runs the test's interpreter, installing
        nothing.
    :return: The finished hook.
    """
    environment = {
        **os.environ,
        WorkflowVariable.PYTHON: sys.executable,
        "TMPDIR": str(markers),
        "CLAUDE_PROJECT_DIR": str(checkout.root),
    }
    if installation is not None:
        del environment[WorkflowVariable.PYTHON]
        environment["CLAUDE_PLUGIN_ROOT"] = str(installation / "plugin")
        environment["HOME"] = str(installation / "home")
    return subprocess.run(
        [str(Path(__file__).parents[1] / "hooks" / "session-start.sh"), event],
        input=json.dumps({"session_id": session}),
        capture_output=True,
        text=True,
        env=environment,
    )


@pytest.fixture
def installation_still_running(tmp_path: Path) -> Path:
    """
    :return: A plugin whose installer is still installing, and a home whose runtime is
        the test's virtual environment.
    """
    installer = tmp_path / "plugin" / "src" / "github_workflow" / "install.py"
    installer.parent.mkdir(parents=True)
    shutil.copy(SessionDataset.INSTALLER_STILL_INSTALLING.value, installer)
    runtime = tmp_path / "home" / ".virtualenvs" / "githubworkflow-runtime"
    runtime.parent.mkdir(parents=True)
    runtime.symlink_to(sys.prefix)
    return tmp_path


def test_a_session_whose_start_was_missed_is_reported_on_its_first_prompt(
    repositories: RepositoriesByOwner, owned_url: str, tmp_path: Path
):
    checkout = repositories.clone(owned_url, "session")

    first = run_session_hook(checkout, HookValue.USER_PROMPT_SUBMIT, "s1", tmp_path)
    second = run_session_hook(checkout, HookValue.USER_PROMPT_SUBMIT, "s1", tmp_path)

    given = json.loads(first.stdout)[HookKey.HOOK_SPECIFIC_OUTPUT]
    assert given[HookKey.HOOK_EVENT_NAME] == HookValue.USER_PROMPT_SUBMIT
    assert second.stdout == ""


def test_a_session_start_that_starts_an_install_leaves_the_report_to_the_first_prompt(
    repositories: RepositoriesByOwner,
    owned_url: str,
    tmp_path: Path,
    installation_still_running: Path,
):
    checkout = repositories.clone(owned_url, "session")

    start = run_session_hook(
        checkout,
        HookValue.SESSION_START,
        "s3",
        tmp_path,
        installation_still_running,
    )
    prompt = run_session_hook(
        checkout,
        HookValue.USER_PROMPT_SUBMIT,
        "s3",
        tmp_path,
        installation_still_running,
    )

    assert HookKey.HOOK_SPECIFIC_OUTPUT not in json.loads(start.stdout)
    given = json.loads(prompt.stdout)[HookKey.HOOK_SPECIFIC_OUTPUT]
    assert given[HookKey.HOOK_EVENT_NAME] == HookValue.USER_PROMPT_SUBMIT


def test_a_session_reported_at_its_start_is_not_reported_again(
    repositories: RepositoriesByOwner, owned_url: str, tmp_path: Path
):
    checkout = repositories.clone(owned_url, "session")
    run_session_hook(checkout, HookValue.SESSION_START, "s2", tmp_path)

    prompt = run_session_hook(checkout, HookValue.USER_PROMPT_SUBMIT, "s2", tmp_path)

    assert prompt.stdout == ""


# %% merged branches


def test_a_session_turns_on_github_s_deletion_of_merged_branches(
    repositories: RepositoriesByOwner,
    owned_url: str,
    settings: WorkflowSettings,
    github: ReplayedApi,
):
    github.answers[("GET", root_path(settings))] = setting(HTTPStatus.OK, False)
    github.answers[("PATCH", root_path(settings))] = setting(HTTPStatus.OK, True)

    start_session(repositories.clone(owned_url, "session"))

    [change] = [sent for sent in github.sent if sent.method == "PATCH"]
    assert change.payload == {RestJSONKey.DELETE_BRANCH_ON_MERGE: True}


def test_a_session_that_may_not_change_settings_links_to_them(
    repositories: RepositoriesByOwner,
    owned_url: str,
    settings: WorkflowSettings,
    github: ReplayedApi,
):
    github.answers[("GET", root_path(settings))] = setting(HTTPStatus.OK, False)
    github.answers[("PATCH", root_path(settings))] = setting(
        HTTPStatus.FORBIDDEN, False
    )
    repository = Repository(settings.owner, RepositoriesByOwner.repository_name)

    finished = start_session(repositories.clone(owned_url, "session"))

    assert (
        repository.settings_url in json.loads(finished.stdout)[HookKey.SYSTEM_MESSAGE]
    )


def test_a_session_whose_repository_deletes_merged_branches_changes_nothing(
    repositories: RepositoriesByOwner, owned_url: str, github: ReplayedApi
):
    start_session(repositories.clone(owned_url, "session"))

    assert {sent.method for sent in github.sent} == {"GET"}


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
        NotesBlock("", "", "", "", "", {NotesSection.STANDING_NOTES: "a note"}).render()
    )
    before = repositories.branches(foreign_url)

    finished = save(checkout)

    assert finished.returncode != 0
    assert repositories.branches(foreign_url) == before
