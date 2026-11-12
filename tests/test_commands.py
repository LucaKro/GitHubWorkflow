"""
Tests for the commands: the session start reads the notes into ``CLAUDE.local.md`` and
never pushes, the save pushes them back, neither writes to anyone else's repository, and
the finding commands that run a test run it on the owner's default branch.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import replace
from http import HTTPStatus
from pathlib import Path

import pytest
from domain_model.claude_code.hooks import HookKey, HookValue
from domain_model.environment import (
    ClaudeCodeVariable,
    GitHubActionsVariable,
    GitHubCredentialVariable,
)
from domain_model.git.revisions import BranchName, TextFiles
from domain_model.github.replayed_api import RecordedAnswer, ReplayedApi
from domain_model.github.repository_client import GitHubRepository, PullRequestListState
from domain_model.github.routes import RepositoryRoute
from domain_model.github.vocabulary import (
    ClosingKeyword,
    IssueEventType,
    IssueState,
    PullRequestState,
    QueryParameter,
    RestJSONKey,
)
from domain_model.locations import GitStateFile, PathEnumeration
from domain_model.repository import GitHubAddress, Repository

import github_workflow
import github_workflow.session_start
from github_workflow.checkout import ProjectCheckout
from github_workflow.command_line import (
    BranchSubcommand,
    FindingSubcommand,
    NotesSubcommand,
    RunnableCommand,
    WorkflowCommand,
)
from github_workflow.discussions import DiscussionPosting, DiscussionSessionLog
from github_workflow.environment import WorkflowVariable
from github_workflow.exceptions import (
    ForeignRepositoryError,
    NoOwnedRemoteError,
    PersonOnlyCommandError,
    UnbuildablePullRequestError,
)
from github_workflow.findings import (
    ClosedBy,
    FindingClosing,
    FindingDraftOpening,
    FindingFiling,
    FindingLabel,
    FindingListing,
    FindingProving,
    FindingRecheck,
    FindingStage,
    FindingUnproving,
    Priority,
    ProvenFindingFiling,
)
from github_workflow.locations import NotesFile, PluginDirectory, ProjectFile
from github_workflow.notes.branch import NotesBranch
from github_workflow.notes.document import NotesBlock, NotesSection
from github_workflow.plugin import ToolRepository
from github_workflow.proofs import BranchProofRunner, FindingTest
from github_workflow.pull_request_overview import PullRequestLabel
from github_workflow.remotes import OwnedRemotes
from github_workflow.report_lines import Speaker, Tone
from github_workflow.session import WorkflowSession
from github_workflow.settings import WorkflowSettings
from github_workflow.upstream import UpstreamSuggestion

from .repositories_by_owner import RepositoriesByOwner
from .test_proofs import ProofDataset

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


class UpstreamDataset(PathEnumeration):
    """
    GitHub's answers about the owner's fork and the repository it was forked from.
    """

    FORK = Path(__file__).parent / "dataset" / "upstream" / "fork.json"
    """
    The owner's scratch repository as a fork of an upstream's.
    """

    UPSTREAM = Path(__file__).parent / "dataset" / "upstream" / "upstream.json"
    """
    The repository the fork was forked from.
    """

    FORK_PULL_REQUESTS = (
        Path(__file__).parent / "dataset" / "upstream" / "fork_pull_requests.json"
    )
    """
    The fork's open pull request from the branch ``feature``.
    """

    OPENED = Path(__file__).parent / "dataset" / "upstream" / "opened.json"
    """
    The pull request opened upstream from it.
    """


# %% GitHub, replayed


@pytest.fixture(autouse=True)
def github(
    monkeypatch: pytest.MonkeyPatch, settings: WorkflowSettings
) -> Iterator[ReplayedApi]:
    """
    :return: GitHub as every command run here reaches it, answering that the owner's
        repository has everything the workflow relies on set up, no workflow, no open
        pull request,
        nothing waiting on the person's review, no findings, and no pull request
        whose branch is left to delete.
    """
    with ReplayedApi() as api:
        api.answers[("GET", root_path(settings))] = answer_branch_deletion_setting(
            HTTPStatus.OK, True
        )
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
        api.answers[("GET", f"/{route.listing(route.workflows)}")] = RecordedAnswer(
            HTTPStatus.OK, json.dumps({RestJSONKey.WORKFLOWS: []})
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


def answer_branch_deletion_setting(status: HTTPStatus, deletes: bool) -> RecordedAnswer:
    """:param status: The status to answer with.
    :param deletes: Whether merged branches are deleted.
    :return: An answer carrying the merged-branch deletion setting."""
    return RecordedAnswer(
        status,
        json.dumps(
            {
                RestJSONKey.DELETE_BRANCH_ON_MERGE: deletes,
                RestJSONKey.HAS_ISSUES: True,
                RestJSONKey.HAS_DISCUSSIONS: True,
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
    notes = NotesBranch.from_settings(
        OwnedRemotes.read(checkout.git, settings).chosen, settings
    )
    notes.fetch()
    return notes


# %% session start


def test_a_session_starts_with_the_notes_and_this_branch_s_progress(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
) -> None:
    writer = repositories.clone(owned_url, "writer")
    NotesBranch.from_settings(
        OwnedRemotes.read(writer.git, settings).chosen, settings
    ).write(
        TextFiles(
            {
                Path(NotesFile.STANDING_NOTES): "a standing note\n",
                NotesFile.progress_file("feature"): "halfway there\n",
            }
        ),
        "Save",
    )
    checkout = repositories.clone(owned_url, "session")
    checkout.git.run("switch", "--quiet", "--create", "feature")

    start_session(checkout)

    sections = NotesBlock.read_sections(checkout.claude_local.read_text())
    assert sections[NotesSection.STANDING_NOTES] == "a standing note"
    assert sections[NotesSection.BRANCH_PROGRESS] == "halfway there"


def test_a_loaded_note_sits_between_its_markers_as_written(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
) -> None:
    note = "a standing note"
    writer = repositories.clone(owned_url, "writer")
    NotesBranch.from_settings(
        OwnedRemotes.read(writer.git, settings).chosen, settings
    ).write(TextFiles({Path(NotesFile.STANDING_NOTES): f"{note}\n"}), "Save")
    checkout = repositories.clone(owned_url, "session")

    start_session(checkout)

    section = NotesSection.STANDING_NOTES
    assert (
        f"{section.start_marker}\n{note}\n{section.end_marker}"
        in checkout.claude_local.read_text()
    )


def test_claude_local_md_is_excluded_from_git_once(
    repositories: RepositoriesByOwner, owned_url: str
) -> None:
    checkout = repositories.clone(owned_url, "session")

    start_session(checkout)
    start_session(checkout)

    exclude = checkout.root / checkout.git.run(
        "rev-parse", "--git-path", str(GitStateFile.EXCLUDE)
    )
    assert exclude.read_text().splitlines().count(str(ProjectFile.CLAUDE_LOCAL)) == 1


def test_a_session_start_pushes_nothing(
    repositories: RepositoriesByOwner, owned_url: str
) -> None:
    before = repositories.branches(owned_url)

    start_session(repositories.clone(owned_url, "session"))

    assert repositories.branches(owned_url) == before


def test_a_session_in_somebody_else_s_repository_loads_nothing(
    repositories: RepositoriesByOwner, foreign_url: str, settings: WorkflowSettings
) -> None:
    checkout = repositories.clone(foreign_url, "theirs")

    finished = start_session(checkout)

    refusal = NoOwnedRemoteError(settings.owner, ("origin",)).error_message()
    assert refusal in finished.stdout
    assert not checkout.claude_local.exists()


def test_a_session_start_is_shown_to_the_person_and_given_to_the_model(
    github: ReplayedApi,
    repositories: RepositoriesByOwner,
    owned_url: str,
    settings: WorkflowSettings,
) -> None:
    route = RepositoryRoute(
        Repository(settings.owner, RepositoriesByOwner.repository_name)
    )
    github.answers[("GET", f"/{route.listing(route.labels)}")] = RecordedAnswer(
        HTTPStatus.OK, json.dumps([{RestJSONKey.NAME: PullRequestLabel.SHELVED}])
    )

    finished = start_session(repositories.clone(owned_url, "session"))

    answer = json.loads(finished.stdout)
    given = answer[HookKey.HOOK_SPECIFIC_OUTPUT]
    assert given[HookKey.HOOK_EVENT_NAME] == HookValue.SESSION_START
    shown = answer[HookKey.SYSTEM_MESSAGE].splitlines()
    plain = given[HookKey.ADDITIONAL_CONTEXT].splitlines()
    assert [line for line in plain if any(line in seen for seen in shown)] == plain
    assert not [line for line in shown if line.startswith(f"\033[1;{Tone.PROBLEM}m")]


def test_a_session_outside_a_checkout_says_so_in_one_line(tmp_path: Path) -> None:
    finished = subprocess.run(
        [sys.executable, "-m", github_workflow.session_start.__name__],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    assert finished.returncode == 0
    assert len(json.loads(finished.stdout)[HookKey.SYSTEM_MESSAGE].splitlines()) == 1


def test_the_hook_answers_even_without_the_package(tmp_path: Path) -> None:
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
    package = tmp_path / "plugin" / PluginDirectory.WORKFLOW_SOURCE / "github_workflow"
    package.mkdir(parents=True)
    shutil.copy(SessionDataset.INSTALLER_STILL_INSTALLING, package / "install.py")
    runtime = tmp_path / "home" / ".virtualenvs" / "githubworkflow-runtime"
    runtime.parent.mkdir(parents=True)
    runtime.symlink_to(sys.prefix)
    return tmp_path


def test_a_session_whose_start_was_missed_is_reported_on_its_first_prompt(
    repositories: RepositoriesByOwner, owned_url: str, tmp_path: Path
) -> None:
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
) -> None:
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
) -> None:
    checkout = repositories.clone(owned_url, "session")
    run_session_hook(checkout, HookValue.SESSION_START, "s2", tmp_path)

    prompt = run_session_hook(checkout, HookValue.USER_PROMPT_SUBMIT, "s2", tmp_path)

    assert prompt.stdout == ""


# %% merged branches


def test_a_session_leaves_merged_branch_deletion_that_is_off_to_the_person(
    repositories: RepositoriesByOwner,
    owned_url: str,
    settings: WorkflowSettings,
    github: ReplayedApi,
) -> None:
    github.answers[("GET", root_path(settings))] = answer_branch_deletion_setting(
        HTTPStatus.OK, False
    )

    start_session(repositories.clone(owned_url, "session"))

    assert {sent.method for sent in github.sent} == {"GET"}


def test_a_session_links_to_the_settings_of_a_feature_that_is_off(
    repositories: RepositoriesByOwner,
    owned_url: str,
    settings: WorkflowSettings,
    github: ReplayedApi,
) -> None:
    github.answers[("GET", root_path(settings))] = answer_branch_deletion_setting(
        HTTPStatus.OK, False
    )
    repository = Repository(settings.owner, RepositoriesByOwner.repository_name)

    finished = start_session(repositories.clone(owned_url, "session"))

    assert (
        repository.settings_url in json.loads(finished.stdout)[HookKey.SYSTEM_MESSAGE]
    )


def test_a_session_whose_repository_deletes_merged_branches_changes_nothing(
    repositories: RepositoriesByOwner, owned_url: str, github: ReplayedApi
) -> None:
    start_session(repositories.clone(owned_url, "session"))

    assert {sent.method for sent in github.sent} == {"GET"}


# %% saving


def test_an_edited_note_is_saved_to_the_notes_branch(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
) -> None:
    checkout = repositories.clone(owned_url, "session")
    start_session(checkout)
    document = checkout.claude_local.read_text()
    marker = NotesSection.STANDING_NOTES.start_marker
    checkout.claude_local.write_text(document.replace(marker, f"{marker}\na new note"))

    save(checkout)

    assert (
        saved_notes(repositories, owned_url, settings).read(NotesFile.STANDING_NOTES)
        == "a new note\n"
    )


def test_saving_without_changes_pushes_nothing(
    repositories: RepositoriesByOwner, owned_url: str
) -> None:
    checkout = repositories.clone(owned_url, "session")
    start_session(checkout)
    before = repositories.branches(owned_url)

    save(checkout)

    assert repositories.branches(owned_url) == before


def test_saving_a_saved_note_again_pushes_nothing(
    repositories: RepositoriesByOwner, owned_url: str
) -> None:
    checkout = repositories.clone(owned_url, "session")
    start_session(checkout)
    document = checkout.claude_local.read_text()
    marker = NotesSection.STANDING_NOTES.start_marker
    checkout.claude_local.write_text(document.replace(marker, f"{marker}\na new note"))
    save(checkout)
    before = repositories.branches(owned_url)

    save(checkout)

    assert repositories.branches(owned_url) == before


def test_saving_in_somebody_else_s_repository_is_refused(
    repositories: RepositoriesByOwner, foreign_url: str
) -> None:
    checkout = repositories.clone(foreign_url, "theirs")
    checkout.claude_local.write_text(
        NotesBlock("", "", "", "", "", {NotesSection.STANDING_NOTES: "a note"}).render()
    )
    before = repositories.branches(foreign_url)

    finished = save(checkout)

    assert finished.returncode != 0
    assert repositories.branches(foreign_url) == before


# %% finding commands that run a test


@pytest.fixture
def finding_checkout(
    repositories: RepositoriesByOwner, owned_url: str, monkeypatch: pytest.MonkeyPatch
) -> ProjectCheckout:
    """:return: A clone of the owner's repository holding an uncommitted finding test
    and a finding's description, the command's working directory."""
    checkout = repositories.clone(owned_url, "session")
    monkeypatch.chdir(checkout.root)
    (checkout.root / "tests").mkdir()
    (checkout.root / "tests" / "test_finding.py").write_text(
        ProofDataset.DOUBLING_SHOWN_WRONG.read_text()
    )
    (checkout.root / "finding.md").write_text("What was found.\n")
    return checkout


@pytest.fixture
def signed_in(github: ReplayedApi) -> str:
    """:return: The login GitHub answers the workflow's token belongs to."""
    login = "a-signed-in-account"
    github.answers[("GET", f"/{RepositoryRoute.authenticated_user()}")] = (
        RecordedAnswer(HTTPStatus.OK, json.dumps({RestJSONKey.LOGIN: login}))
    )
    return login


def build_step(checkout: ProjectCheckout, *arguments: str) -> object:
    """:param checkout: The checkout the command runs in.
    :param arguments: The command line.
    :return: The step it asks for."""
    parsed = RunnableCommand.parser().parse_args(list(arguments))
    return WorkflowSession(checkout.root, WorkflowSettings()).step(parsed)


def owner_s_github(settings: WorkflowSettings) -> GitHubRepository:
    """:param settings: The workflow's settings.
    :return: The owner's scratch repository, as the replayed GitHub serves it."""
    return GitHubRepository.from_environment(
        Repository(settings.owner, RepositoriesByOwner.repository_name)
    )


def build_proof_runner(checkout: ProjectCheckout) -> BranchProofRunner:
    """:param checkout: The checkout.
    :return: Runs tests on its owner's default branch with an interpreter named
    ``project-python``."""
    remote = OwnedRemotes.read(checkout.git, WorkflowSettings()).chosen
    return BranchProofRunner(
        remote.branch(RepositoriesByOwner.default_branch), "project-python"
    )


def read_finding_test(checkout: ProjectCheckout) -> FindingTest:
    """:param checkout: The checkout.
    :return: The finding test it holds."""
    return FindingTest.read(checkout, checkout.root / "tests" / "test_finding.py")


def test_a_finding_filed_with_a_test_is_proven_on_the_default_branch(
    finding_checkout: ProjectCheckout, settings: WorkflowSettings
) -> None:
    step = build_step(
        finding_checkout,
        WorkflowCommand.FINDING,
        FindingSubcommand.FILE,
        "--title=A title",
        "--body-file=finding.md",
        f"--priority={Priority.HIGH.level}",
        "--test=tests/test_finding.py",
        "--python=project-python",
    )

    github = owner_s_github(settings)
    assert step == ProvenFindingFiling(
        github,
        "A title",
        "What was found.\n",
        Priority.HIGH,
        read_finding_test(finding_checkout),
        build_proof_runner(finding_checkout),
    )


def test_a_finding_filed_without_a_test_runs_none(
    finding_checkout: ProjectCheckout, settings: WorkflowSettings
) -> None:
    step = build_step(
        finding_checkout,
        WorkflowCommand.FINDING,
        FindingSubcommand.FILE,
        "--title=A title",
        "--body-file=finding.md",
        f"--priority={Priority.HIGH.level}",
    )

    github = owner_s_github(settings)
    assert step == FindingFiling(github, "A title", "What was found.\n", Priority.HIGH)


def test_proving_runs_the_test_on_the_default_branch(
    finding_checkout: ProjectCheckout, settings: WorkflowSettings
) -> None:
    step = build_step(
        finding_checkout,
        WorkflowCommand.FINDING,
        FindingSubcommand.PROVE,
        "3",
        "--test=tests/test_finding.py",
        "--python=project-python",
    )

    github = owner_s_github(settings)
    assert step == FindingProving(
        github,
        3,
        read_finding_test(finding_checkout),
        build_proof_runner(finding_checkout),
    )


def answer_open_pull_request(
    github: ReplayedApi, settings: WorkflowSettings, **changes: object
) -> None:
    """
    Have GitHub answer that pull request 56 of the owner's repository is open from the
    branch ``below``.

    :param github: The replayed GitHub.
    :param settings: The workflow's settings.
    :param changes: Top-level fields of the pull request to answer differently.
    """
    repository = Repository(settings.owner, RepositoriesByOwner.repository_name)
    below = json.loads(UpstreamDataset.FORK_PULL_REQUESTS.value.read_text())[0]
    below["head"]["ref"] = "below"
    below["head"]["repo"]["full_name"] = repository.full_name
    below.update(changes)
    github.answers[("GET", f"/{RepositoryRoute(repository).pull_request(56)}")] = (
        RecordedAnswer(HTTPStatus.OK, json.dumps(below))
    )


def test_proving_on_a_pull_request_runs_the_test_on_its_branch(
    github: ReplayedApi, finding_checkout: ProjectCheckout, settings: WorkflowSettings
) -> None:
    answer_open_pull_request(github, settings)

    step = build_step(
        finding_checkout,
        WorkflowCommand.FINDING,
        FindingSubcommand.PROVE,
        "3",
        "--test=tests/test_finding.py",
        "--on=56",
        "--python=project-python",
    )

    runner = build_proof_runner(finding_checkout)
    assert step.runner == replace(
        runner, branch=runner.branch.remote.branch(BranchName("below"))
    )


def test_proving_on_a_branch_runs_the_test_there(
    finding_checkout: ProjectCheckout, settings: WorkflowSettings
) -> None:
    step = build_step(
        finding_checkout,
        WorkflowCommand.FINDING,
        FindingSubcommand.PROVE,
        "3",
        "--test=tests/test_finding.py",
        "--on=without-pull-request",
        "--python=project-python",
    )

    runner = build_proof_runner(finding_checkout)
    assert step.runner == replace(
        runner, branch=runner.branch.remote.branch(BranchName("without-pull-request"))
    )


def test_rechecking_on_a_pull_request_runs_the_test_on_its_branch(
    github: ReplayedApi,
    finding_checkout: ProjectCheckout,
    settings: WorkflowSettings,
    signed_in: str,
) -> None:
    answer_open_pull_request(github, settings)

    step = build_step(
        finding_checkout,
        WorkflowCommand.FINDING,
        FindingSubcommand.RECHECK,
        "3",
        "--on=56",
        "--python=project-python",
    )

    runner = build_proof_runner(finding_checkout)
    assert step.runner == replace(
        runner, branch=runner.branch.remote.branch(BranchName("below"))
    )


def test_proving_on_a_closed_pull_request_is_refused(
    github: ReplayedApi, finding_checkout: ProjectCheckout, settings: WorkflowSettings
) -> None:
    answer_open_pull_request(github, settings, state=PullRequestState.CLOSED)

    with pytest.raises(UnbuildablePullRequestError):
        build_step(
            finding_checkout,
            WorkflowCommand.FINDING,
            FindingSubcommand.PROVE,
            "3",
            "--test=tests/test_finding.py",
            "--on=56",
            "--python=project-python",
        )


def test_marking_unproven_keeps_the_reason(
    finding_checkout: ProjectCheckout, settings: WorkflowSettings
) -> None:
    step = build_step(
        finding_checkout,
        WorkflowCommand.FINDING,
        FindingSubcommand.MARK_UNPROVEN,
        "3",
        "--reason=Needs a live server",
    )

    github = owner_s_github(settings)
    assert step == FindingUnproving(github, 3, "Needs a live server")


def test_a_recheck_trusts_the_owner_and_the_signed_in_account(
    finding_checkout: ProjectCheckout, settings: WorkflowSettings, signed_in: str
) -> None:
    step = build_step(
        finding_checkout,
        WorkflowCommand.FINDING,
        FindingSubcommand.RECHECK,
        "3",
        "--python=project-python",
    )

    assert step == FindingRecheck(
        owner_s_github(settings),
        build_proof_runner(finding_checkout),
        {settings.owner, signed_in},
        3,
    )


def test_a_fixed_finding_is_closed_through_the_command_line(
    finding_checkout: ProjectCheckout, settings: WorkflowSettings, signed_in: str
) -> None:
    step = build_step(
        finding_checkout,
        WorkflowCommand.FINDING,
        FindingSubcommand.CLOSE,
        "3",
        "--fixed-by=157",
        "--python=project-python",
    )

    github = owner_s_github(settings)
    git = finding_checkout.git
    notes = NotesBranch.from_settings(OwnedRemotes.read(git, settings).chosen, settings)
    assert step == FindingClosing(
        github,
        3,
        build_proof_runner(finding_checkout),
        {settings.owner, signed_in},
        RepositoriesByOwner.default_branch,
        157,
        DiscussionSessionLog(
            github, DiscussionPosting(notes), git.run("branch", "--show-current")
        ),
    )


def test_a_draft_naming_a_finding_rechecks_it_first(
    finding_checkout: ProjectCheckout, settings: WorkflowSettings, signed_in: str
) -> None:
    step = build_step(
        finding_checkout,
        WorkflowCommand.DRAFT,
        "--title=A title",
        "--body-file=finding.md",
        "--finding=3",
        "--python=project-python",
    )

    assert isinstance(step, FindingDraftOpening)
    assert step.recheck == FindingRecheck(
        owner_s_github(settings),
        build_proof_runner(finding_checkout),
        {settings.owner, signed_in},
        3,
    )


def test_a_draft_building_on_a_pull_request_rechecks_on_its_branch(
    github: ReplayedApi,
    finding_checkout: ProjectCheckout,
    settings: WorkflowSettings,
    signed_in: str,
) -> None:
    """
    A fix that needs what the pull request below brings is proven against it, not
    against the default branch.
    """
    repository = Repository(settings.owner, RepositoriesByOwner.repository_name)
    below = json.loads(UpstreamDataset.FORK_PULL_REQUESTS.value.read_text())[0]
    below["head"]["ref"] = "below"
    github.answers[("GET", f"/{RepositoryRoute(repository).pull_request(56)}")] = (
        RecordedAnswer(HTTPStatus.OK, json.dumps(below))
    )

    step = build_step(
        finding_checkout,
        WorkflowCommand.DRAFT,
        "--title=A title",
        "--body-file=finding.md",
        "--finding=3",
        "--on=56",
        "--python=project-python",
    )

    assert isinstance(step, FindingDraftOpening)
    runner = build_proof_runner(finding_checkout)
    assert step.recheck.runner == replace(
        runner, branch=runner.branch.remote.branch(BranchName("below"))
    )


# %% commenting on and editing a finding


def non_reads(api: ReplayedApi) -> list[tuple[str, str]]:
    """:param api: The replayed GitHub.
    :return: Every request that was no read, as method and path."""
    return [(sent.method, sent.path) for sent in api.sent if sent.method != "GET"]


def test_a_finding_is_commented_on_through_the_command_line(
    github: ReplayedApi,
    repositories: RepositoriesByOwner,
    owned_url: str,
    settings: WorkflowSettings,
) -> None:
    checkout = repositories.clone(owned_url, "session")
    (checkout.root / "comment.md").write_text("Found more.\n")
    route = RepositoryRoute(
        Repository(settings.owner, RepositoriesByOwner.repository_name)
    )
    open_finding(github, route)
    path = f"/{route.issue_comments(1)}"
    github.answers[("POST", path)] = RecordedAnswer(
        HTTPStatus.CREATED, json.dumps({RestJSONKey.HTML_URL: "https://github.com/c"})
    )

    run(
        github_workflow.__name__,
        checkout,
        WorkflowCommand.FINDING,
        FindingSubcommand.COMMENT,
        "1",
        "--body-file",
        "comment.md",
    )

    assert non_reads(github) == [("POST", path)]


@pytest.mark.parametrize(
    "subcommand", [FindingSubcommand.COMMENT, FindingSubcommand.EDIT]
)
def test_a_finding_on_another_of_the_owner_s_repositories_is_reached(
    finding_checkout: ProjectCheckout, subcommand: FindingSubcommand
) -> None:
    workflow = Repository(WorkflowSettings().owner, "GitHubWorkflow")

    step = build_step(
        finding_checkout,
        WorkflowCommand.FINDING,
        subcommand,
        "148",
        "--body-file=finding.md",
        f"--repository={workflow.full_name}",
    )

    assert step.issues == GitHubRepository.from_environment(workflow)


@pytest.mark.parametrize(
    "subcommand", [FindingSubcommand.COMMENT, FindingSubcommand.EDIT]
)
def test_a_finding_on_somebody_else_s_repository_is_not_reached(
    finding_checkout: ProjectCheckout, subcommand: FindingSubcommand
) -> None:
    with pytest.raises(ForeignRepositoryError):
        build_step(
            finding_checkout,
            WorkflowCommand.FINDING,
            subcommand,
            "148",
            "--body-file=finding.md",
            f"--repository={RepositoriesByOwner.foreign_owner}/project",
        )


def test_a_finding_s_text_is_edited_through_the_command_line(
    github: ReplayedApi,
    repositories: RepositoriesByOwner,
    owned_url: str,
    settings: WorkflowSettings,
) -> None:
    checkout = repositories.clone(owned_url, "session")
    (checkout.root / "finding.md").write_text("What was found, corrected.\n")
    route = RepositoryRoute(
        Repository(settings.owner, RepositoriesByOwner.repository_name)
    )
    open_finding(github, route)
    path = f"/{route.issue(1)}"
    github.answers[("PATCH", path)] = RecordedAnswer(HTTPStatus.OK, json.dumps({}))

    run(
        github_workflow.__name__,
        checkout,
        WorkflowCommand.FINDING,
        FindingSubcommand.EDIT,
        "1",
        "--body-file",
        "finding.md",
    )

    assert non_reads(github) == [("PATCH", path)]


def open_finding(api: ReplayedApi, route: RepositoryRoute) -> None:
    """
    Answer that issue 1 is an open, accepted finding.

    :param api: The replayed GitHub.
    :param route: The owner's repository's routes.
    """
    api.answers[("GET", f"/{route.issue(1)}")] = RecordedAnswer(
        HTTPStatus.OK,
        json.dumps(
            {
                RestJSONKey.NUMBER: 1,
                RestJSONKey.TITLE: "A finding",
                RestJSONKey.STATE: IssueState.OPEN,
                RestJSONKey.LABELS: [{RestJSONKey.NAME: FindingStage.ACCEPTED}],
            }
        ),
    )


# %% opening a fork's pull request upstream


def answer_as_a_fork(api: ReplayedApi, settings: WorkflowSettings) -> Repository:
    """
    Answer that the owner's scratch repository is a fork, with an open pull request
    from ``feature``, and no labels yet, and that its upstream has none from it yet.

    :param api: The replayed GitHub.
    :param settings: The workflow's settings.
    :return: The upstream.
    """
    fork = RepositoryRoute(
        Repository(settings.owner, RepositoriesByOwner.repository_name)
    )
    upstream_data = json.loads(UpstreamDataset.UPSTREAM.value.read_text())
    upstream = Repository.parse(upstream_data[RestJSONKey.FULL_NAME])
    route = RepositoryRoute(upstream)
    api.answers[("GET", f"/{fork.root}")] = RecordedAnswer.from_file(
        HTTPStatus.OK, UpstreamDataset.FORK.value
    )
    api.answers[
        ("GET", f"/{fork.pull_requests_for_head(settings.owner, 'feature')}")
    ] = RecordedAnswer.from_file(
        HTTPStatus.OK, UpstreamDataset.FORK_PULL_REQUESTS.value
    )
    api.answers[
        ("GET", f"/{route.pull_requests_for_head(settings.owner, 'feature')}")
    ] = RecordedAnswer(HTTPStatus.OK, "[]")
    api.answers[("GET", f"/{route.root}")] = RecordedAnswer.from_file(
        HTTPStatus.OK, UpstreamDataset.UPSTREAM.value
    )
    api.answers[("POST", f"/{route.pull_requests}")] = RecordedAnswer.from_file(
        HTTPStatus.CREATED, UpstreamDataset.OPENED.value
    )
    api.answers[("POST", f"/{fork.issue_comments(3)}")] = RecordedAnswer(
        HTTPStatus.CREATED, json.dumps({RestJSONKey.HTML_URL: "https://github.com/c"})
    )
    api.answers[("GET", f"/{fork.listing(fork.labels)}")] = RecordedAnswer(
        HTTPStatus.OK, "[]"
    )
    api.answers[("POST", f"/{fork.labels}")] = RecordedAnswer(HTTPStatus.CREATED, "{}")
    api.answers[("PUT", f"/{fork.issue_labels(3)}")] = RecordedAnswer(
        HTTPStatus.OK, "[]"
    )
    return upstream


def test_the_person_opens_the_fork_s_pull_request_upstream(
    github: ReplayedApi,
    repositories: RepositoriesByOwner,
    owned_url: str,
    settings: WorkflowSettings,
) -> None:
    upstream = answer_as_a_fork(github, settings)
    fork = Repository(settings.owner, RepositoriesByOwner.repository_name)

    finished = run(
        github_workflow.__name__,
        repositories.clone(owned_url, "anywhere"),
        WorkflowCommand.UPSTREAM,
        fork.full_name,
        "feature",
    )

    fork_route = RepositoryRoute(fork)
    assert finished.returncode == 0
    assert non_reads(github) == [
        ("POST", f"/{RepositoryRoute(upstream).pull_requests}"),
        ("POST", f"/{fork_route.issue_comments(3)}"),
        ("POST", f"/{fork_route.labels}"),
        ("PUT", f"/{fork_route.issue_labels(3)}"),
    ]


def test_a_session_opening_a_pull_request_upstream_is_refused(
    github: ReplayedApi,
    repositories: RepositoriesByOwner,
    owned_url: str,
    settings: WorkflowSettings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answer_as_a_fork(github, settings)
    monkeypatch.setenv(ClaudeCodeVariable.COMMAND_MARKER, "1")
    fork = Repository(settings.owner, RepositoriesByOwner.repository_name)

    finished = run(
        github_workflow.__name__,
        repositories.clone(owned_url, "anywhere"),
        WorkflowCommand.UPSTREAM,
        fork.full_name,
        "feature",
    )

    assert finished.returncode != 0
    assert non_reads(github) == []


def test_a_refusal_is_reported_as_its_reason_without_a_traceback(
    github: ReplayedApi,
    repositories: RepositoriesByOwner,
    owned_url: str,
    settings: WorkflowSettings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ClaudeCodeVariable.COMMAND_MARKER, "1")
    fork = Repository(settings.owner, RepositoriesByOwner.repository_name)

    finished = run(
        github_workflow.__name__,
        repositories.clone(owned_url, "anywhere"),
        WorkflowCommand.UPSTREAM,
        fork.full_name,
        "feature",
    )

    refusal = PersonOnlyCommandError(WorkflowCommand.UPSTREAM)
    assert (finished.returncode, finished.stderr) == (
        1,
        f"{Speaker.WORKFLOW.says(str(refusal))}\n",
    )


def test_a_draft_on_a_fork_ends_with_the_command_for_the_person(
    github: ReplayedApi,
    repositories: RepositoriesByOwner,
    owned_url: str,
    settings: WorkflowSettings,
) -> None:
    answer_as_a_fork(github, settings)
    checkout = repositories.clone(owned_url, "session")
    checkout.git.run("switch", "--quiet", "--create", "feature")
    (checkout.root / "body.md").write_text("What it does.\n")

    step = build_step(
        checkout,
        WorkflowCommand.DRAFT,
        "--title=Add the thing",
        f"--body-file={checkout.root / 'body.md'}",
    )

    fork = Repository(settings.owner, RepositoriesByOwner.repository_name)
    assert step.ending == UpstreamSuggestion(owner_s_github(settings), fork)


def test_a_rewritten_description_of_a_fork_s_pull_request_keeps_the_upstream_line(
    github: ReplayedApi,
    repositories: RepositoriesByOwner,
    owned_url: str,
    settings: WorkflowSettings,
) -> None:
    answer_as_a_fork(github, settings)
    fork = Repository(settings.owner, RepositoriesByOwner.repository_name)
    route = RepositoryRoute(fork)
    opened = json.loads(UpstreamDataset.FORK_PULL_REQUESTS.value.read_text())[0]
    github.answers[("GET", f"/{route.pull_request(3)}")] = RecordedAnswer(
        HTTPStatus.OK, json.dumps(opened)
    )
    github.answers[("PATCH", f"/{route.pull_request(3)}")] = RecordedAnswer(
        HTTPStatus.OK, json.dumps(opened)
    )
    checkout = repositories.clone(owned_url, "session")
    (checkout.root / "body.md").write_text("What it does, after the review.\n")

    run(
        github_workflow.__name__,
        checkout,
        WorkflowCommand.DESCRIBE,
        "3",
        f"--body-file={checkout.root / 'body.md'}",
    )

    written = [sent.payload for sent in github.sent if sent.method == "PATCH"]
    suggestion = UpstreamSuggestion(owner_s_github(settings), fork)
    assert written == [
        {
            RestJSONKey.BODY: suggestion.append_once(
                "What it does, after the review.\n", "feature"
            )
        }
    ]


def test_a_rewritten_description_keeps_the_line_closing_its_finding(
    github: ReplayedApi,
    repositories: RepositoriesByOwner,
    owned_url: str,
    settings: WorkflowSettings,
) -> None:
    route = RepositoryRoute(
        Repository(settings.owner, RepositoriesByOwner.repository_name)
    )
    opened = json.loads(UpstreamDataset.FORK_PULL_REQUESTS.value.read_text())[0]
    closing = ClosingKeyword.FIXES.reference(148)
    opened[RestJSONKey.BODY] = f"What it does.\n\n{closing}"
    for method in ("GET", "PATCH"):
        github.answers[(method, f"/{route.pull_request(3)}")] = RecordedAnswer(
            HTTPStatus.OK, json.dumps(opened)
        )
    checkout = repositories.clone(owned_url, "session")
    (checkout.root / "body.md").write_text("What it does, after the review.\n")

    run(
        github_workflow.__name__,
        checkout,
        WorkflowCommand.DESCRIBE,
        "3",
        f"--body-file={checkout.root / 'body.md'}",
    )

    [written] = [sent.payload for sent in github.sent if sent.method == "PATCH"]
    assert closing in written[RestJSONKey.BODY]


def test_describe_without_a_number_rewrites_the_work_branch_s_own_pull_request(
    github: ReplayedApi,
    repositories: RepositoriesByOwner,
    owned_url: str,
    settings: WorkflowSettings,
) -> None:
    route = RepositoryRoute(
        Repository(settings.owner, RepositoriesByOwner.repository_name)
    )
    github.answers[
        ("GET", f"/{route.pull_requests_for_head(settings.owner, 'feature')}")
    ] = RecordedAnswer.from_file(
        HTTPStatus.OK, UpstreamDataset.FORK_PULL_REQUESTS.value
    )
    checkout = repositories.clone(owned_url, "session")
    checkout.git.run("switch", "--quiet", "--create", "feature")
    (checkout.root / "body.md").write_text("What it does.\n")

    step = build_step(
        checkout, WorkflowCommand.DESCRIBE, f"--body-file={checkout.root / 'body.md'}"
    )

    opened = json.loads(UpstreamDataset.FORK_PULL_REQUESTS.value.read_text())[0]
    assert step.number == opened[RestJSONKey.NUMBER]


# %% findings on another of the owner's repositories


def filing_elsewhere(directory: Path, repository: str, *more: str) -> object:
    """
    :param directory: Where the command runs, no checkout needed.
    :param repository: The repository named.
    :param more: Further arguments.
    :return: The step filing a finding there.
    """
    body = directory / "finding.md"
    body.write_text("What was refused, and why it should not have been.\n")
    arguments = RunnableCommand.parser().parse_args(
        [
            WorkflowCommand.FINDING,
            FindingSubcommand.FILE,
            f"--repository={repository}",
            "--priority=medium",
            "--title=A read was refused",
            f"--body-file={body}",
            *more,
        ]
    )
    return WorkflowSession(directory, WorkflowSettings()).step(arguments)


def test_a_finding_is_filed_on_the_workflow_from_outside_any_checkout(
    tmp_path: Path,
) -> None:
    step = filing_elsewhere(tmp_path, ToolRepository.WORKFLOW)

    board = GitHubRepository.from_environment(Repository.parse(ToolRepository.WORKFLOW))
    assert step == FindingFiling(
        board,
        "A read was refused",
        (tmp_path / "finding.md").read_text(),
        Priority.MEDIUM,
    )


def test_findings_are_listed_on_the_workflow_from_outside_any_checkout(
    tmp_path: Path,
) -> None:
    arguments = RunnableCommand.parser().parse_args(
        [
            WorkflowCommand.FINDING,
            FindingSubcommand.LIST,
            f"--repository={ToolRepository.WORKFLOW}",
        ]
    )

    step = WorkflowSession(tmp_path, WorkflowSettings()).step(arguments)

    repository = Repository.parse(ToolRepository.WORKFLOW)
    board = GitHubRepository.from_environment(repository)
    assert step == FindingListing(board, repository)


def test_a_finding_on_somebody_else_s_repository_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ForeignRepositoryError):
        filing_elsewhere(tmp_path, f"{RepositoriesByOwner.foreign_owner}/project")


def test_a_finding_filed_elsewhere_carries_no_test(tmp_path: Path) -> None:
    """
    The test proving a finding runs on a checkout of the repository it is filed on.
    """
    with pytest.raises(SystemExit):
        filing_elsewhere(tmp_path, ToolRepository.WORKFLOW, "--test=test_it.py")


# %% following the upstream


def test_a_fork_s_main_behind_its_upstream_is_synced_through_the_command_line(
    github: ReplayedApi,
    repositories: RepositoriesByOwner,
    owned_url: str,
    settings: WorkflowSettings,
) -> None:
    """
    The branches are compared and the fork moved with git, so GitHub's API is asked for
    nothing but the fork's details.
    """
    fork = RepositoryRoute(
        Repository(settings.owner, RepositoriesByOwner.repository_name)
    )
    github.answers[("GET", f"/{fork.root}")] = RecordedAnswer.from_file(
        HTTPStatus.OK, UpstreamDataset.FORK.value
    )
    checkout = repositories.clone(owned_url, "session")
    parent = json.loads(UpstreamDataset.FORK.value.read_text())[RestJSONKey.PARENT]
    upstream = repositories.root / f"{parent[RestJSONKey.FULL_NAME]}.git"
    default = RepositoriesByOwner.default_branch
    checkout.git.run(
        "init", "--quiet", "--bare", f"--initial-branch={default}", str(upstream)
    )
    checkout.git.run("push", "--quiet", str(upstream), f"HEAD:refs/heads/{default}")
    writer = repositories.clone(f"file://{upstream}", "upstream-writer").git
    writer.run("commit", "--quiet", "--allow-empty", "--message", "Upstream moved on")
    writer.run("push", "--quiet", str(upstream), f"HEAD:refs/heads/{default}")
    checkout.git.run(
        "config", f"url.file://{repositories.root}/.insteadOf", f"{GitHubAddress.WEB}/"
    )

    run(github_workflow.__name__, checkout, WorkflowCommand.SYNC, "--upstream")

    fork_tip = checkout.git.run("ls-remote", owned_url, default).split()[0]
    assert (non_reads(github), fork_tip) == ([], writer.run("rev-parse", "HEAD"))


# %% taking in the default branch


def test_the_default_branch_s_new_commits_are_merged_through_the_command_line(
    github: ReplayedApi,
    repositories: RepositoriesByOwner,
    owned_url: str,
    settings: WorkflowSettings,
) -> None:
    checkout = repositories.clone(owned_url, "session")
    git = checkout.git
    git.run("switch", "--quiet", "--create", "feature")
    git.run("commit", "--quiet", "--allow-empty", "--message", "Add a")
    git.run("push", "--quiet", "--set-upstream", "origin", "feature")
    other = repositories.clone(owned_url, "other").git
    other.run("commit", "--quiet", "--allow-empty", "--message", "Main moved on")
    other.run("push", "--quiet", "origin", f"HEAD:{RepositoriesByOwner.default_branch}")
    route = RepositoryRoute(
        Repository(settings.owner, RepositoriesByOwner.repository_name)
    )
    github.answers[
        ("GET", f"/{route.pull_requests_for_head(settings.owner, 'feature')}")
    ] = RecordedAnswer(HTTPStatus.OK, "[]")

    run(github_workflow.__name__, checkout, WorkflowCommand.SYNC, "--base")

    assert RepositoriesByOwner.is_ancestor(
        git, other.run("rev-parse", "HEAD"), git.run("rev-parse", "HEAD")
    )


def test_another_open_pull_request_s_commits_are_merged_into_the_work_branch(
    github: ReplayedApi,
    repositories: RepositoriesByOwner,
    owned_url: str,
    settings: WorkflowSettings,
) -> None:
    repository = Repository(settings.owner, RepositoriesByOwner.repository_name)
    other = repositories.clone(owned_url, "other").git
    other.run("switch", "--quiet", "--create", "below")
    other.run("commit", "--quiet", "--allow-empty", "--message", "Make tests load")
    other.run("push", "--quiet", "origin", "below")
    checkout = repositories.clone(owned_url, "session")
    git = checkout.git
    git.run("switch", "--quiet", "--create", "feature")
    git.run("commit", "--quiet", "--allow-empty", "--message", "Fix it")
    git.run("push", "--quiet", "--set-upstream", "origin", "feature")
    below = json.loads(UpstreamDataset.FORK_PULL_REQUESTS.value.read_text())[0]
    below["number"] = 56
    below["head"]["ref"] = "below"
    below["head"]["repo"]["full_name"] = repository.full_name
    route = RepositoryRoute(repository)
    github.answers[("GET", f"/{route.pull_request(56)}")] = RecordedAnswer(
        HTTPStatus.OK, json.dumps(below)
    )
    github.answers[
        ("GET", f"/{route.pull_requests_for_head(settings.owner, 'feature')}")
    ] = RecordedAnswer(HTTPStatus.OK, "[]")

    run(github_workflow.__name__, checkout, WorkflowCommand.SYNC, "--on", "56")

    assert RepositoriesByOwner.is_ancestor(
        git, other.run("rev-parse", "HEAD"), git.run("rev-parse", "HEAD")
    )


def test_a_conflicting_merge_is_resolved_and_finished_through_the_command_line(
    github: ReplayedApi,
    repositories: RepositoriesByOwner,
    owned_url: str,
    settings: WorkflowSettings,
) -> None:
    checkout = repositories.clone(owned_url, "session")
    git = checkout.git
    git.run("switch", "--quiet", "--create", "feature")
    (checkout.root / "shared.txt").write_text("the branch's line\n")
    git.run("add", "shared.txt")
    git.run("commit", "--quiet", "--message", "Change it here")
    git.run("push", "--quiet", "--set-upstream", "origin", "feature")
    other = repositories.clone(owned_url, "other").git
    (other.working_directory / "shared.txt").write_text("main's line\n")
    other.run("add", "shared.txt")
    other.run("commit", "--quiet", "--message", "Change it on main")
    other.run("push", "--quiet", "origin", f"HEAD:{RepositoriesByOwner.default_branch}")
    route = RepositoryRoute(
        Repository(settings.owner, RepositoriesByOwner.repository_name)
    )
    github.answers[
        ("GET", f"/{route.pull_requests_for_head(settings.owner, 'feature')}")
    ] = RecordedAnswer(HTTPStatus.OK, "[]")

    run(github_workflow.__name__, checkout, WorkflowCommand.SYNC, "--base")
    (checkout.root / "shared.txt").write_text("main's line\nthe branch's line\n")
    run(
        github_workflow.__name__,
        checkout,
        WorkflowCommand.SYNC,
        "--continue",
        "shared.txt",
    )

    assert RepositoriesByOwner.is_ancestor(
        git, other.run("rev-parse", "HEAD"), git.run("rev-parse", "HEAD")
    )
    assert (
        checkout.root / "shared.txt"
    ).read_text() == "main's line\nthe branch's line\n"


def test_discarding_a_branch_closes_its_open_draft(
    github: ReplayedApi,
    repositories: RepositoriesByOwner,
    owned_url: str,
    settings: WorkflowSettings,
) -> None:
    checkout = repositories.clone(owned_url, "session")
    git = checkout.git
    git.run("switch", "--quiet", "--create", "tried")
    git.run("commit", "--quiet", "--allow-empty", "--message", "Try")
    git.run("push", "--quiet", "--set-upstream", "origin", "tried")
    route = RepositoryRoute(
        Repository(settings.owner, RepositoriesByOwner.repository_name)
    )
    draft = json.loads(UpstreamDataset.FORK_PULL_REQUESTS.value.read_text())[0]
    draft["head"]["ref"] = "tried"
    github.answers[
        ("GET", f"/{route.pull_requests_for_head(settings.owner, 'tried')}")
    ] = RecordedAnswer(HTTPStatus.OK, json.dumps([draft]))
    github.answers[("GET", f"/{route.listing(route.labels)}")] = RecordedAnswer(
        HTTPStatus.OK, json.dumps([{RestJSONKey.NAME: ClosedBy.SESSION}])
    )
    github.answers[("POST", f"/{route.issue_labels(3)}")] = RecordedAnswer(
        HTTPStatus.OK, "[]"
    )
    github.answers[("POST", f"/{route.issue_comments(3)}")] = RecordedAnswer(
        HTTPStatus.CREATED, json.dumps({RestJSONKey.HTML_URL: "https://github.com/c"})
    )
    github.answers[("PATCH", f"/{route.pull_request(3)}")] = RecordedAnswer(
        HTTPStatus.OK, json.dumps(draft)
    )

    run(
        github_workflow.__name__,
        checkout,
        WorkflowCommand.BRANCH,
        BranchSubcommand.DISCARD,
        "tried",
    )

    closed = [
        sent.payload
        for sent in github.sent
        if (sent.method, sent.path) == ("PATCH", f"/{route.pull_request(3)}")
    ]
    assert closed == [{RestJSONKey.STATE: PullRequestState.CLOSED}]


# %% the work branch's own pull request


def test_the_work_branch_s_pull_request_is_labelled_through_the_command_line(
    github: ReplayedApi,
    repositories: RepositoriesByOwner,
    owned_url: str,
    settings: WorkflowSettings,
) -> None:
    route = RepositoryRoute(
        Repository(settings.owner, RepositoriesByOwner.repository_name)
    )
    github.answers[
        ("GET", f"/{route.pull_requests_for_head(settings.owner, 'feature')}")
    ] = RecordedAnswer.from_file(
        HTTPStatus.OK, UpstreamDataset.FORK_PULL_REQUESTS.value
    )
    github.answers[("GET", f"/{route.listing(route.labels)}")] = RecordedAnswer(
        HTTPStatus.OK, json.dumps([{RestJSONKey.NAME: "bug-fix"}])
    )
    github.answers[("POST", f"/{route.issue_labels(3)}")] = RecordedAnswer(
        HTTPStatus.OK, "[]"
    )
    checkout = repositories.clone(owned_url, "session")
    checkout.git.run("switch", "--quiet", "--create", "feature")

    run(github_workflow.__name__, checkout, WorkflowCommand.LABEL, "--add", "bug-fix")

    assert non_reads(github) == [("POST", f"/{route.issue_labels(3)}")]


# %% completing labels picked on GitHub


def test_listing_completes_a_stage_picked_on_github(
    github: ReplayedApi,
    repositories: RepositoriesByOwner,
    owned_url: str,
    settings: WorkflowSettings,
) -> None:
    route = RepositoryRoute(
        Repository(settings.owner, RepositoriesByOwner.repository_name)
    )
    carried = [FindingStage.UNREVIEWED, Priority.MEDIUM, FindingStage.ACCEPTED]
    issue = {
        RestJSONKey.NUMBER: 61,
        RestJSONKey.TITLE: "A finding",
        RestJSONKey.STATE: IssueState.OPEN,
        RestJSONKey.LABELS: [{RestJSONKey.NAME: label} for label in carried],
    }
    for stage in (FindingStage.UNREVIEWED, FindingStage.ACCEPTED):
        listing = route.listing(
            route.issues(),
            {QueryParameter.LABELS: stage, QueryParameter.STATE: IssueState.OPEN},
        )
        github.answers[("GET", f"/{listing}")] = RecordedAnswer(
            HTTPStatus.OK, json.dumps([issue])
        )
    github.answers[("GET", f"/{route.issue(61)}")] = RecordedAnswer(
        HTTPStatus.OK, json.dumps(issue)
    )
    events = [
        {
            RestJSONKey.EVENT: IssueEventType.LABELED,
            RestJSONKey.LABEL: {RestJSONKey.NAME: label},
        }
        for label in carried
    ]
    github.answers[("GET", f"/{route.listing(route.issue_events(61))}")] = (
        RecordedAnswer(HTTPStatus.OK, json.dumps(events))
    )
    github.answers[("GET", f"/{route.listing(route.labels)}")] = RecordedAnswer(
        HTTPStatus.OK,
        json.dumps([{RestJSONKey.NAME: label} for label in FindingLabel.every_label]),
    )
    removed = f"/{route.issue_label(61, FindingStage.UNREVIEWED)}"
    github.answers[("DELETE", removed)] = RecordedAnswer(HTTPStatus.OK, "[]")
    checkout = repositories.clone(owned_url, "session")

    run(
        github_workflow.__name__,
        checkout,
        WorkflowCommand.FINDING,
        FindingSubcommand.LIST,
    )

    assert ("DELETE", removed) in non_reads(github)
