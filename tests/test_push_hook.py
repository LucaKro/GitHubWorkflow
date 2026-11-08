"""
Tests for :mod:`github_workflow.push_hook`: a push from a Claude Code session, however
it is run, goes only to the owner's repositories and never to the default branch; a
person's own pushes pass unchecked.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from basstler_domain_model.environment import ClaudeCodeVariable
from basstler_domain_model.git.commands import (
    GitCommandRunner,
    ReferenceUpdate,
    RemoteBranch,
)

from github_workflow.exceptions import (
    DefaultBranchWriteError,
    ForeignPushError,
    UnknownDefaultBranchError,
)
from github_workflow.push_hook import PushCheck, PushHook
from github_workflow.report_lines import Tone
from github_workflow.settings import WorkflowSettings

from .repositories_by_owner import RepositoriesByOwner

# %% helpers


def update_of(branch: str) -> ReferenceUpdate:
    """
    :param branch: The branch on the remote a push changes.
    :return: A push of a new commit to it.
    """
    reference = RemoteBranch(RepositoriesByOwner.default_branch, branch).reference
    return ReferenceUpdate(reference, "1" * 40, reference, "2" * 40)


def hooked(repositories: RepositoriesByOwner, url: str) -> GitCommandRunner:
    """
    :param repositories: Where to clone.
    :param url: The repository to clone.
    :return: A clone of it with the push hook installed and a new commit to push.
    """
    checkout = repositories.clone(url, "hooked")
    PushHook(checkout, Path(sys.executable)).install()
    checkout.git.run("commit", "--quiet", "--allow-empty", "--message", "New work")
    return checkout.git


@pytest.fixture
def in_claude_code(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Marks the test's commands as run by a Claude Code session.
    """
    monkeypatch.setenv(ClaudeCodeVariable.COMMAND_MARKER, "1")


# %% the check


def test_a_push_to_a_foreign_repository_is_refused(
    repositories: RepositoriesByOwner, foreign_url: str, settings: WorkflowSettings
) -> None:
    git = repositories.clone(foreign_url, "foreign").git
    check = PushCheck(git, "origin", foreign_url, settings)

    with pytest.raises(ForeignPushError):
        check.raise_if_forbidden([update_of("work")])


def test_a_push_to_the_default_branch_is_refused(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
) -> None:
    git = repositories.clone(owned_url, "owned").git
    check = PushCheck(git, "origin", owned_url, settings)

    with pytest.raises(DefaultBranchWriteError):
        check.raise_if_forbidden([update_of(RepositoriesByOwner.default_branch)])


def test_a_push_of_a_work_branch_to_the_owner_is_allowed(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
) -> None:
    git = repositories.clone(owned_url, "owned").git
    check = PushCheck(git, "origin", owned_url, settings)

    assert check.raise_if_forbidden([update_of("work")]) is None


def test_a_push_to_a_remote_whose_default_branch_cannot_be_read_is_refused(
    repositories: RepositoriesByOwner,
    owned_url: str,
    settings: WorkflowSettings,
    tmp_path: Path,
) -> None:
    git = repositories.clone(owned_url, "owned").git
    unreachable = f"file://{tmp_path / 'missing' / settings.owner / 'project.git'}"
    check = PushCheck(git, unreachable, unreachable, settings)

    with pytest.raises(UnknownDefaultBranchError):
        check.raise_if_forbidden([update_of("work")])


# %% the hook on a push


def test_a_session_s_push_to_the_default_branch_is_refused_by_the_hook(
    repositories: RepositoriesByOwner, owned_url: str, in_claude_code: None
) -> None:
    git = hooked(repositories, owned_url)
    before = repositories.branches(owned_url)

    pushed = git.attempt("push", "origin", "HEAD:refs/heads/main")

    assert not pushed.succeeded
    assert repositories.branches(owned_url) == before


def test_a_session_s_push_to_a_foreign_repository_is_refused_by_the_hook(
    repositories: RepositoriesByOwner, foreign_url: str, in_claude_code: None
) -> None:
    git = hooked(repositories, foreign_url)
    before = repositories.branches(foreign_url)

    pushed = git.attempt("push", "origin", "HEAD:refs/heads/work")

    assert not pushed.succeeded
    assert repositories.branches(foreign_url) == before


def test_a_session_s_push_of_a_work_branch_passes_the_hook(
    repositories: RepositoriesByOwner, owned_url: str, in_claude_code: None
) -> None:
    git = hooked(repositories, owned_url)

    git.run("push", "--quiet", "origin", "HEAD:refs/heads/work")

    assert f"{git.commit_at('HEAD')}\trefs/heads/work" in repositories.branches(
        owned_url
    )


def test_a_person_s_own_push_passes_the_hook_unchecked(
    repositories: RepositoriesByOwner, owned_url: str
) -> None:
    git = hooked(repositories, owned_url)

    git.run("push", "--quiet", "origin", "HEAD:refs/heads/main")

    assert f"{git.commit_at('HEAD')}\trefs/heads/main" in repositories.branches(
        owned_url
    )


# %% installing the hook


def test_the_hook_is_written_where_core_hooks_path_points(
    repositories: RepositoriesByOwner, owned_url: str
) -> None:
    checkout = repositories.clone(owned_url, "owned")
    hooks = checkout.root / "shared-hooks"
    checkout.git.run("config", "core.hooksPath", str(hooks))
    hook = PushHook(checkout, Path(sys.executable))

    hook.install()

    assert (hooks / "pre-push").read_text() == hook.script


def test_a_checkout_s_own_pre_push_hook_is_kept(
    repositories: RepositoriesByOwner, owned_url: str
) -> None:
    checkout = repositories.clone(owned_url, "owned")
    hook = PushHook(checkout, Path(sys.executable))
    own = Path(__file__).parent / "dataset" / "push_hook" / "checkout_s_own.sh"
    hook.path.write_text(own.read_text())

    hook.install()

    assert hook.path.read_text() == own.read_text()


def test_keeping_a_checkout_s_own_pre_push_hook_asks_for_action(
    repositories: RepositoriesByOwner, owned_url: str
) -> None:
    checkout = repositories.clone(owned_url, "owned")
    hook = PushHook(checkout, Path(sys.executable))
    own = Path(__file__).parent / "dataset" / "push_hook" / "checkout_s_own.sh"
    hook.path.write_text(own.read_text())

    lines = hook.install()

    assert [line.tone for line in lines] == [Tone.ACTION]


def test_an_earlier_hook_of_the_workflow_s_is_replaced(
    repositories: RepositoriesByOwner, owned_url: str, tmp_path: Path
) -> None:
    checkout = repositories.clone(owned_url, "owned")
    PushHook(checkout, tmp_path / "an-earlier-runtime" / "python").install()
    hook = PushHook(checkout, Path(sys.executable))

    hook.install()

    assert hook.path.read_text() == hook.script
