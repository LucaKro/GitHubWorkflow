"""
The checkout's ``pre-push`` hook: every push from a Claude Code session, run by the
workflow or any other program, is checked against the owner's rules; a person's own
pushes pass unchecked.

Usage, as git runs the hook: ``python -m github_workflow.push_hook <remote> <url>``,
with git's reference updates on standard input.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from dataclasses import dataclass
from enum import auto
from pathlib import Path

from domain_model.environment import ClaudeCodeVariable
from domain_model.git.remotes import ReferenceUpdate, Remote
from domain_model.locations import GitStateFile
from domain_model.templates import Placeholder

from github_workflow.checkout import ProjectCheckout
from github_workflow.exceptions import (
    DefaultBranchWriteError,
    ForeignPushError,
    UnknownDefaultBranchError,
)
from github_workflow.locations import WorkflowTemplate
from github_workflow.plugin import FileMode
from github_workflow.report_lines import ReportLine, Speaker, Tone
from github_workflow.settings import WorkflowSettings

# %% the template's placeholders


class PushHookPlaceholder(Placeholder):
    """
    The names the ``pre-push`` hook's template leaves to be filled in.
    """

    MARKER_VARIABLE = auto()
    """
    The variable set only in commands a Claude Code session runs.
    """

    PYTHON = auto()
    """
    The interpreter the package is installed in.
    """

    MODULE = auto()
    """
    The module a hook runs.
    """


# %% the check


@dataclass(frozen=True)
class PushCheck:
    """
    A push about to run, allowed only to a repository of the owner's and only when it
    leaves the default branch alone.
    """

    destination: Remote
    """
    The remote pushed to, named as git names it to the hook: its name, or its URL when
    the push names no remote.
    """

    settings: WorkflowSettings
    """
    Whose repositories may be pushed to.
    """

    def raise_if_forbidden(self, updates: Sequence[ReferenceUpdate]) -> None:
        """
        :param updates: The references the push changes.
        :raises ForeignPushError: If the URL names no repository of the owner's.
        :raises UnknownDefaultBranchError: If the remote's default branch cannot be
            read.
        :raises DefaultBranchWriteError: If the push changes the default branch.
        """
        repository = self.destination.repository
        if repository is None or not self.settings.owns(repository):
            raise ForeignPushError(self.destination.push_url, self.settings.owner)
        default_branch = self.destination.default_branch()
        if default_branch is None:
            raise UnknownDefaultBranchError(self.destination.name)
        reference = self.destination.branch(default_branch).reference
        if any(update.remote_reference == reference for update in updates):
            raise DefaultBranchWriteError(default_branch)


# %% the hook


@dataclass(frozen=True)
class PushHook:
    """
    The checkout's ``pre-push`` hook, running :class:`PushCheck` on every push from a
    Claude Code session.
    """

    checkout: ProjectCheckout
    """
    The checkout whose pushes are checked.
    """

    python: Path
    """
    The interpreter the package is installed in, which the hook runs the check with.
    """

    @property
    def path(self) -> Path:
        """
        Where git runs the checkout's ``pre-push`` hook from.
        """
        return self.checkout.git.git_path(GitStateFile.PRE_PUSH_HOOK)

    @property
    def script(self) -> str:
        """
        The hook, as written into the checkout.
        """
        return Placeholder.fill(
            WorkflowTemplate.PRE_PUSH_HOOK.read_text(),
            {
                PushHookPlaceholder.MARKER_VARIABLE: ClaudeCodeVariable.COMMAND_MARKER,
                PushHookPlaceholder.PYTHON: str(self.python),
                PushHookPlaceholder.MODULE: PushCheck.__module__,
            },
        )

    def install(self) -> list[ReportLine]:
        """
        Write the hook, replacing an earlier one of the workflow's, but never a ``pre-
        push`` hook of the checkout's own.

        :return: Nothing when the hook was written; one line saying why it was not
            otherwise.
        """
        path = self.path
        if path.exists() and PushCheck.__module__ not in path.read_text():
            return [
                ReportLine(
                    Speaker.WORKFLOW.says(
                        f"{path} is a pre-push hook of the checkout's own, so pushes "
                        f"run outside the workflow's commands go unchecked; ask the "
                        f"person whether to merge in the workflow's from "
                        f"{WorkflowTemplate.PRE_PUSH_HOOK}"
                    ),
                    Tone.ACTION,
                )
            ]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.script)
        path.chmod(FileMode.RUNNABLE)
        return []


# %% entry point


def main() -> None:
    """
    Check the push git is about to run, as its ``pre-push`` hook.
    """
    destination, url = sys.argv[1:3]
    checkout = ProjectCheckout.containing(Path.cwd())
    updates = [ReferenceUpdate.from_line(line) for line in sys.stdin if line.strip()]
    remote = Remote.from_push_url(checkout.git, destination, url)
    PushCheck(remote, WorkflowSettings()).raise_if_forbidden(updates)


if __name__ == "__main__":
    main()
