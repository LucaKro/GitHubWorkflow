"""
The writes a session makes to git and GitHub, each one step that checks the
:class:`WritePolicy` before it writes anything and reports what it did in one line.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from basstler_domain_model.git.commands import (
    GitCommandRunner,
    ProposedPush,
    RemoteBranch,
)
from basstler_domain_model.github.pull_request_fields import (
    PullRequestField,
    PullRequestHead,
)
from basstler_domain_model.github.repository_client import (
    PullRequestOpener,
    PullRequestReader,
    PullRequestWriter,
)
from basstler_domain_model.github.vocabulary import IssueState
from basstler_domain_model.repository import GitHubAddress, Repository

from github_workflow.exceptions import (
    BranchDeletedFromGitHubError,
    BranchNotPushedError,
    DetachedHeadError,
    ForeignRepositoryCloneError,
    NotADraftError,
    PushRefusedError,
    UnpushedCommitsError,
)
from github_workflow.notes.saving import NotesSave
from github_workflow.policy import WritePolicy
from github_workflow.settings import WorkflowSettings
from github_workflow.stacks import StackPlacement

# %% one step


class WorkflowStep(ABC):
    """
    One write a session asks the workflow for.
    """

    @abstractmethod
    def run(self) -> str:
        """
        Make the write.

        :return: What was done, in one line.
        """


# %% branches


@dataclass(frozen=True)
class BranchStart(WorkflowStep):
    """
    A new work branch, started from GitHub's copy of the default branch or of another
    branch - or from the local branch, when GitHub has none of that name - and checked
    out. Started from GitHub's default branch, it also fast-forwards the local default
    branch to it.
    """

    policy: WritePolicy
    """
    Where the branch is started from.
    """

    name: str
    """
    The new branch.
    """

    base: str | None = None
    """
    The branch to start from, the default branch when ``None``.
    """

    def run(self) -> str:
        base = RemoteBranch(
            self.policy.remote.name, self.base or self.policy.default_branch
        )
        git = self.policy.checkout.git
        fetched = git.fetch_branch(base.remote, base.name, base.remote)
        if fetched.succeeded:
            git.create_branch(self.name, base.tracking_reference)
            started = f"on {self.name}, started from {base.remote}/{base.name}"
            if base.name != self.policy.default_branch:
                return started
            return f"{started}{self._fast_forward_local(base)}"
        if git.commit_or_none(base.reference) is None:
            fetched.raise_if_failed()
        git.create_branch(self.name, base.name)
        return f"on {self.name}, started from the local {base.name}"

    def _fast_forward_local(self, base: RemoteBranch) -> str:
        """
        Fast-forward the local copy of *base* to GitHub's, unless it has commits of its
        own.

        :param base: The default branch, as just fetched.
        :return: What happened to the local copy, as an addition to the report; empty
            when there is none or it is up to date.
        """
        git = self.policy.checkout.git
        local = git.commit_or_none(base.reference)
        if local is None or local == git.commit_at(base.tracking_reference):
            return ""
        if not git.contains(local, base.tracking_reference):
            return f"; local {base.name} kept: it has commits GitHub's lacks"
        moved = git.fast_forward_branch(base.name, base.tracking_reference)
        if not moved.succeeded:
            return f"; local {base.name} kept: it is checked out in another worktree"
        return f"; local {base.name} fast-forwarded to it"


@dataclass(frozen=True)
class BranchSwitch(WorkflowStep):
    """
    Switching to an existing branch.
    """

    policy: WritePolicy
    """
    The checkout switched in.
    """

    name: str
    """
    The branch to switch to.
    """

    def run(self) -> str:
        self.policy.checkout.git.switch_to(self.name)
        return f"on {self.name}"


# %% committing and pushing


@dataclass(frozen=True)
class CommitWork(WorkflowStep):
    """
    A commit of named files on the work branch.
    """

    policy: WritePolicy
    """
    What may be committed where.
    """

    message: str
    """
    The commit message asked for.
    """

    paths: Sequence[Path]
    """
    The files to commit, as they are in the working tree.
    """

    def run(self) -> str:
        branch = self.policy.work_branch()
        commit = self.policy.checkout.git.commit(
            self.policy.commit_message(self.message), self.paths
        )
        return f"committed {commit[:7]} on {branch}"


@dataclass(frozen=True)
class PushWork(WorkflowStep):
    """
    A push of the work branch to the owner's remote, never forced, after which the
    branch tracks its copy there.
    """

    policy: WritePolicy
    """
    What may be pushed where.
    """

    def run(self) -> str:
        branch = RemoteBranch(self.policy.remote.name, self.policy.work_branch())
        pushed = self.policy.checkout.git.push(
            ProposedPush(
                branch.remote, f"{branch.name}:{branch.reference}", sets_upstream=True
            )
        )
        if not pushed.succeeded:
            raise PushRefusedError(branch.name, pushed.error_output)
        return f"pushed {branch.name} to {self.policy.remote.repository.full_name}"


# %% pull requests


@dataclass(frozen=True)
class DraftOpening(WorkflowStep):
    """
    A draft pull request for the pushed work branch, onto the default branch or stacked
    on another pull request.
    """

    policy: WritePolicy
    """
    What may be opened where.
    """

    opener: PullRequestOpener
    """
    Opens the pull request.
    """

    placement: StackPlacement
    """
    Stacks it on another pull request, when asked to.
    """

    title: str
    """
    The pull request's title.
    """

    body: str
    """
    Its description.
    """

    below: int | None = None
    """
    The pull request to stack it on, ``None`` to target the default branch.
    """

    def run(self) -> str:
        branch = RemoteBranch(self.policy.remote.name, self.policy.work_branch())
        if not self.policy.checkout.git.has_remote_branch(branch):
            raise BranchNotPushedError(branch.name)
        base = (
            self.policy.default_branch
            if self.below is None
            else PullRequestHead.from_record(
                self.placement.pull_requests.pull_request(self.below), self.below
            ).branch
        )
        number = self.opener.open_draft(branch.name, base, self.title, self.body)
        opened = f"opened draft #{number}: {branch.name} onto {base}"
        if self.below is None:
            return opened
        stack = self.placement.place(self.below, number)
        return f"{opened}, in stack {stack.number}"


@dataclass(frozen=True)
class DescriptionRewrite(WorkflowStep):
    """
    A new description for an open draft pull request on the owner's repository; a pull
    request that is ready for review or closed is the person's to change.
    """

    pull_requests: PullRequestReader
    """
    Reads the pull request.
    """

    writer: PullRequestWriter
    """
    Writes its description.
    """

    number: int
    """
    The pull request.
    """

    body: str
    """
    The new description.
    """

    def run(self) -> str:
        record = self.pull_requests.pull_request(self.number)
        is_open = PullRequestField.STATE.read(record, self.number) == IssueState.OPEN
        if not is_open or not PullRequestField.DRAFT.read(record, self.number):
            raise NotADraftError(self.number)
        self.writer.set_description(self.number, self.body)
        return f"rewrote the description of draft #{self.number}"


# %% bringing a branch up to date


@dataclass(frozen=True)
class BranchSync(WorkflowStep):
    """
    The checked-out branch brought up to date with GitHub's copy: fast-forwarded, or
    moved to the copy GitHub rebased when every local commit had been pushed.

    :raises BranchDeletedFromGitHubError: If GitHub had the branch and no longer has it.
    :raises GitCommandFailed: If GitHub cannot be reached, or the fetch fails although
        GitHub has the branch.
    """

    policy: WritePolicy
    """
    The checkout and the remote synced with.
    """

    def run(self) -> str:
        git = self.policy.checkout.git
        name = git.checked_out_branch()
        if not name:
            raise DetachedHeadError()
        branch = RemoteBranch(self.policy.remote.name, name)
        last_seen = git.commit_or_none(branch.tracking_reference)
        fetched = git.fetch_branch(branch.remote, name, branch.remote)
        if not fetched.succeeded and git.has_remote_branch(branch):
            fetched.raise_if_failed()
        if not fetched.succeeded and last_seen is not None:
            raise BranchDeletedFromGitHubError(name)
        if not fetched.succeeded:
            return f"{name} is not on GitHub yet"
        on_github = git.commit_at(branch.tracking_reference)
        local = git.commit_at("HEAD")
        if local == on_github:
            return f"{name} is up to date"
        if git.contains(local, on_github):
            git.fast_forward(on_github).raise_if_failed()
            return f"{name} fast-forwarded to GitHub's"
        if git.contains(on_github, local):
            return f"{name} is ahead of GitHub's: push it"
        if last_seen is None or not git.contains(local, last_seen):
            raise UnpushedCommitsError(name)
        git.reset_kept(on_github)
        return f"{name} moved to the branch GitHub rebased"


# %% stacks and notes


@dataclass(frozen=True)
class StackPlacing(WorkflowStep):
    """
    One pull request put on top of another in a native stack.
    """

    placement: StackPlacement
    """
    Places it.
    """

    below: int
    """
    The pull request to build on.
    """

    above: int
    """
    The pull request to put on top.
    """

    def run(self) -> str:
        stack = self.placement.place(self.below, self.above)
        layers = " <- ".join(
            f"#{pull_request.number} ({pull_request.branch})"
            for pull_request in stack.pull_requests
        )
        return f"stack {stack.number} on {stack.base}: {layers}"


@dataclass(frozen=True)
class NotesSaving(WorkflowStep):
    """
    The notes block saved to the notes branch.
    """

    save: NotesSave
    """
    The save.
    """

    def run(self) -> str:
        saved = self.save.run()
        if not saved:
            return (
                f"nothing changed since the last save to {self.save.notes.branch.name}"
            )
        line = f"saved {', '.join(map(str, saved))} to {self.save.notes.branch.name}"
        checked_out = self.save.checkout.git.checked_out_branch()
        if self.save.progress_branch in {"", checked_out}:
            return line
        return (
            f"{line}; the progress is {self.save.progress_branch}'s, loaded at session "
            f"start, not the checked-out {checked_out}'s"
        )


# %% other repositories


@dataclass(frozen=True)
class RepositoryCloning(WorkflowStep):
    """
    A clone of another of the owner's repositories, refused for anyone else's.
    """

    repository: Repository
    """
    The repository to clone.
    """

    directory: Path
    """
    The directory the clone is made in, under the repository's name.
    """

    settings: WorkflowSettings
    """
    Whose repositories may be cloned.
    """

    hosting_root: str = GitHubAddress.WEB
    """
    Where repositories are kept as ``<root>/owner/name.git``.
    """

    def run(self) -> str:
        if not self.settings.owns(self.repository):
            raise ForeignRepositoryCloneError(self.repository, self.settings.owner)
        checkout = self.directory / self.repository.name
        GitCommandRunner.clone(
            self.repository.clone_url_under(self.hosting_root), checkout
        )
        return f"cloned {self.repository} into {checkout}"
