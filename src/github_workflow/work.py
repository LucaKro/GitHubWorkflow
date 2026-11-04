"""
The writes a session makes to git and GitHub, each one step that checks the
:class:`WritePolicy` before it writes anything and reports what it did in one line.
"""

from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from basstler_domain_model.git.commands import (
    GitCommandRunner,
    ProposedPush,
    RemoteBranch,
)
from basstler_domain_model.github.repository_client import (
    PullRequestOpener,
    PullRequestReader,
    PullRequestWriter,
)
from basstler_domain_model.github.vocabulary import PullRequestState
from basstler_domain_model.repository import GitHubAddress, Repository

from github_workflow.checkout import ProjectCheckout
from github_workflow.exceptions import (
    BranchDeletedFromGitHubError,
    BranchNotPushedError,
    DetachedHeadError,
    NotADraftError,
    PushRefusedError,
    UnpushedCommitsError,
)
from github_workflow.notes.saving import NotesSave
from github_workflow.policy import WritePolicy
from github_workflow.push_hook import PushHook
from github_workflow.settings import WorkflowSettings
from github_workflow.stacks import StackPlacement

if TYPE_CHECKING:
    from basstler_domain_model.github.repository_client import GitHubRepository

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
class LocalBranchFollowing:
    """
    A local branch fast-forwarded to GitHub's copy, unless it has commits of its own.
    """

    git: GitCommandRunner
    """
    Runs git in the checkout.
    """

    def follow(self, branch: RemoteBranch) -> str:
        """
        :param branch: The branch, as just fetched.
        :return: What happened to the local copy, as an addition to a report; empty
            when there is none or it is up to date.
        """
        local = self.git.commit_or_none(branch.reference)
        if local is None or local == self.git.commit_at(branch.tracking_reference):
            return ""
        if not self.git.contains(local, branch.tracking_reference):
            return f"; local {branch.name} kept: it has commits GitHub's lacks"
        if self.git.checked_out_branch() == branch.name:
            self.git.fast_forward(branch.tracking_reference).raise_if_failed()
            return f"; local {branch.name} fast-forwarded to it"
        moved = self.git.fast_forward_branch(branch.name, branch.tracking_reference)
        if not moved.succeeded:
            return f"; local {branch.name} kept: it is checked out in another worktree"
        return f"; local {branch.name} fast-forwarded to it"


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
        fetched = git.fetch_branch(base)
        if fetched.succeeded:
            git.create_branch(self.name, base.tracking_reference)
            started = f"on {self.name}, started from {base.remote}/{base.name}"
            if base.name != self.policy.default_branch:
                return started
            return f"{started}{LocalBranchFollowing(git).follow(base)}"
        if git.commit_or_none(base.reference) is None:
            fetched.raise_if_failed()
        git.create_branch(self.name, base.name)
        return f"on {self.name}, started from the local {base.name}"


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


class DescriptionEnding(ABC):
    """
    What a draft's description ends with, given its branch.
    """

    @abstractmethod
    def appended_to(self, body: str, branch: str) -> str:
        """
        :param body: A draft's description.
        :param branch: The draft's branch.
        :return: The description with its ending.
        """


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

    ending: DescriptionEnding | None = None
    """
    What the description of a draft onto the default branch ends with, ``None`` for
    nothing.
    """

    def run(self) -> str:
        branch = RemoteBranch(self.policy.remote.name, self.policy.work_branch())
        if not self.policy.checkout.git.has_remote_branch(branch):
            raise BranchNotPushedError(branch.name)
        base = (
            self.policy.default_branch
            if self.below is None
            else self.placement.pull_requests.pull_request(self.below).head.branch
        )
        body = (
            self.ending.appended_to(self.body, branch.name)
            if self.ending is not None and self.below is None
            else self.body
        )
        number = self.opener.open_draft(branch.name, base, self.title, body)
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
        pull_request = self.pull_requests.pull_request(self.number)
        if pull_request.state is not PullRequestState.OPEN or not pull_request.draft:
            raise NotADraftError(self.number)
        self.writer.set_description(self.number, self.body)
        return f"rewrote the description of draft #{self.number}"


# %% bringing a branch up to date


class TrackingReferenceWrite(StrEnum):
    """
    How the reflog names a write of a remote-tracking reference from what GitHub holds,
    compared as the start of the entry.
    """

    FETCH = "fetch"
    """
    A fetch stored the branch.
    """

    PULL = "pull"
    """
    A pull stored the branch.
    """

    PUSH = "update by push"
    """
    A push sent the branch.
    """


class PullRequestBranches(ABC):
    """
    The branches pull requests on the owner's repository were opened from.
    """

    @abstractmethod
    def opened_from(self, branch: str) -> bool:
        """
        :param branch: A branch of the owner's repository.
        :return: Whether a pull request, open or closed, was opened from it.
        """


@dataclass(frozen=True)
class GitHubPullRequestBranches(PullRequestBranches):
    """
    The branches pull requests were opened from, as GitHub lists the pull requests.
    """

    github: GitHubRepository
    """
    The owner's repository on GitHub.
    """

    repository: str
    """
    The repository's full name, which a pull request's head names when it is from
    this repository.
    """

    def opened_from(self, branch: str) -> bool:
        return any(
            pull_request.head.repository == self.repository
            and pull_request.head.branch == branch
            for pull_request in self.github.all_pull_requests()
        )


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

    pull_request_branches: PullRequestBranches
    """
    The branches pull requests were opened from, which shows a branch was on GitHub.
    """

    def run(self) -> str:
        git = self.policy.checkout.git
        name = git.checked_out_branch()
        if not name:
            raise DetachedHeadError()
        branch = RemoteBranch(self.policy.remote.name, name)
        last_seen = git.commit_or_none(branch.tracking_reference)
        fetched = git.fetch_branch(branch)
        if not fetched.succeeded and git.has_remote_branch(branch):
            fetched.raise_if_failed()
        if (
            not fetched.succeeded
            and last_seen is not None
            and self.was_on_github(branch)
        ):
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

    def was_on_github(self, branch: RemoteBranch) -> bool:
        """
        :param branch: A branch GitHub does not have, whose remote-tracking reference
            the checkout has.
        :return: Whether GitHub had it: a fetch or a push wrote its remote-tracking
            reference, or a pull request was opened from it.
        """
        reflog = self.policy.checkout.git.attempt(
            "reflog", "show", "--format=%gs", branch.tracking_reference
        )
        entries = reflog.output.splitlines() if reflog.succeeded else []
        writes = tuple(TrackingReferenceWrite)
        if any(entry.startswith(writes) for entry in entries):
            return True
        return self.pull_request_branches.opened_from(branch.name)


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
    A clone of a repository, the owner's or anyone else's, carrying the workflow's push
    hook, so a session's push from it meets the same rules as from its own checkout:
    nothing is pushed to somebody else's repository, which is cloned only to be read.
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
    Whose repositories a clone may push to.
    """

    hosting_root: str = GitHubAddress.WEB
    """
    Where repositories are kept as ``<root>/owner/name.git``.
    """

    def run(self) -> str:
        destination = self.directory / self.repository.name
        GitCommandRunner.clone(
            self.repository.clone_url_under(self.hosting_root), destination
        )
        checkout = ProjectCheckout(GitCommandRunner(destination))
        refused = PushHook(checkout, Path(sys.executable)).install()
        cloned = [f"cloned {self.repository} into {destination}"]
        if not self.settings.owns(self.repository):
            cloned.append(
                f"it is {self.repository.owner}'s, so it is only read: nothing is "
                f"pushed from it"
            )
        return "; ".join([*cloned, *(line.text for line in refused)])
