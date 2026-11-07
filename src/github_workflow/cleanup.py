"""
Branches GitHub kept although their pull request is closed - closed without merging, or
merged before GitHub deleted merged branches - and branches discarded as thrown away.
Listed at session start, deleted by the cleanup command - or, where the session may not
delete branches, handed to an Actions workflow on the notes branch. The cleanup command
also removes the clones of somebody else's repositories no session uses any more.
"""

from __future__ import annotations

import shutil
import time
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import timedelta
from enum import StrEnum
from pathlib import Path
from typing import Self

from basstler_domain_model.git.commands import GitCommandRunner, RemoteBranch
from basstler_domain_model.github.repository_client import (
    GitHubRepository,
    PullRequestsFromForks,
)
from basstler_domain_model.github.rest_models import RestPullRequest
from basstler_domain_model.github.vocabulary import PullRequestState

from github_workflow.command_line import WorkflowCommand
from github_workflow.exceptions import (
    DetachedHeadError,
    NothingToDiscardError,
    UndiscardableBranchError,
)
from github_workflow.hooks import ReportLine, Tone
from github_workflow.locations import GitStateFile, NotesFile, WorkflowTemplate
from github_workflow.notes.branch import NotesBranch
from github_workflow.policy import WritePolicy
from github_workflow.remotes import OwnedRemote
from github_workflow.report_section import ReportSection
from github_workflow.work import PullRequestRetirement, SessionLog, WorkflowStep

# %% branches listed with their commits


@dataclass(frozen=True)
class BranchTips:
    """
    Branches, each with the commit it may be deleted at, as the notes branch lists them.
    """

    commits: Mapping[str, str] = field(default_factory=dict)
    """
    Each branch, and the commit it may be deleted at.
    """

    @classmethod
    def from_text(cls, text: str | None) -> Self:
        """
        :param text: The list as the notes branch keeps it, ``None`` when it has none.
        :return: The branches it names.
        """
        pairs = (line.split() for line in (text or "").splitlines() if line.strip())
        return cls({branch: commit for branch, commit in pairs})

    def to_text(self) -> str:
        """:return: The list as the notes branch keeps it."""
        return "".join(
            f"{branch} {commit}\n" for branch, commit in sorted(self.commits.items())
        )


# %% discarded branches


@dataclass(frozen=True)
class DiscardedBranches(BranchTips):
    """
    The branches discarded as thrown away, each with the commit it was at when
    discarded.
    """

    def with_branch(self, branch: str, commit: str) -> DiscardedBranches:
        """
        :param branch: A branch to discard.
        :param commit: The commit it is at.
        :return: These branches and that one.
        """
        return DiscardedBranches({**self.commits, branch: commit})


@dataclass(frozen=True)
class BranchDiscard(WorkflowStep):
    """
    A pushed branch marked as thrown away on the notes branch, so the cleanup deletes it
    while it is still at the commit it was discarded at, and its open pull requests
    closed.
    """

    policy: WritePolicy
    """
    The checkout and the owner's remote the branch is on.
    """

    notes: NotesBranch
    """
    The notes branch, which lists the discarded branches.
    """

    pull_requests: PullRequestsFromForks
    """
    Finds the pull requests open from the branch.
    """

    retirement: PullRequestRetirement
    """
    Closes them.
    """

    name: str | None = None
    """
    The branch to discard, the checked-out one when ``None``.
    """

    def run(self) -> str:
        git = self.policy.checkout.git
        branch = self.name or git.checked_out_branch()
        if not branch:
            raise DetachedHeadError()
        if branch in {self.policy.default_branch, self.notes.branch.name}:
            raise UndiscardableBranchError(branch)
        tip = git.remote_branch_tip(RemoteBranch(self.policy.remote.name, branch))
        if tip is None:
            raise NothingToDiscardError(branch)
        self.notes.fetch()
        listed = self.notes.read(NotesFile.DISCARDED_BRANCHES.value)
        discarded = DiscardedBranches.from_text(listed).with_branch(branch, tip)
        self.notes.write(
            {NotesFile.DISCARDED_BRANCHES.value: discarded.to_text()},
            f"Discard {branch}",
        )
        owner = self.policy.remote.repository.owner
        closed = [
            pull_request.number
            for pull_request in self.pull_requests.pull_requests_from(owner, branch)
            if pull_request.state is PullRequestState.OPEN
        ]
        for number in closed:
            self.retirement.retire(
                number, f"Discarded: its branch {branch} is marked for deletion."
            )
        command = WorkflowCommand.command_line(WorkflowCommand.CLEANUP)
        marked = f"{branch} marked for deletion; `{command}` deletes it"
        if not closed:
            return marked
        listed = ", ".join(f"#{number}" for number in closed)
        return f"{marked}; closed its pull request {listed}: tell the person"


# %% which branches


@dataclass(frozen=True)
class KeptBranches:
    """
    The branches on the owner's repository, and its pull requests, from which the
    branches ready for deletion follow.
    """

    tips: Mapping[str, str]
    """
    Each branch on the repository, and the commit it is at.
    """

    pull_requests: Sequence[RestPullRequest]
    """
    Every pull request on the repository, open or closed.
    """

    repository: str
    """
    The repository's full name, which a pull request's head names when it is from
    this repository.
    """

    protected: frozenset[str]
    """
    The branches never deleted: the default branch and the notes branch.
    """

    discarded: DiscardedBranches = field(default_factory=DiscardedBranches)
    """
    The branches discarded as thrown away.
    """

    def ready(self) -> list[str]:
        """
        :return: Each branch whose pull request is closed, or that was discarded, and
            that is still at the commit it was closed or discarded at, with no open pull
            request from or into it; never a protected one.
        """
        in_use = set()
        closed_heads: dict[str, set[str]] = {}
        for pull_request in self.pull_requests:
            is_open = pull_request.state is PullRequestState.OPEN
            if is_open:
                in_use.add(pull_request.base)
            head = pull_request.head
            if head.repository != self.repository:
                continue
            if is_open:
                in_use.add(head.branch)
            else:
                closed_heads.setdefault(head.branch, set()).add(head.commit)
        return sorted(
            branch
            for branch, tip in self.tips.items()
            if branch not in self.protected
            and branch not in in_use
            and (
                tip in closed_heads.get(branch, set())
                or tip == self.discarded.commits.get(branch)
            )
        )

    @classmethod
    def read(
        cls,
        git: GitCommandRunner,
        remote: OwnedRemote,
        github: GitHubRepository,
        notes: NotesBranch,
    ) -> KeptBranches:
        """
        :param git: Runs git in the checkout.
        :param remote: The owner's remote.
        :param github: The owner's repository on GitHub.
        :param notes: The notes branch, as last fetched.
        :return: The repository's branches and pull requests, read at once, and the
            branches the notes branch lists as discarded.
        """
        with ThreadPoolExecutor() as pool:
            listed = pool.submit(git.run, "ls-remote", "--heads", remote.name)
            pull_requests = pool.submit(github.all_pull_requests)
            default_branch = pool.submit(github.default_branch)
        tips = {}
        for line in listed.result().splitlines():
            commit, reference = line.split()
            tips[reference.removeprefix(RemoteBranch(remote.name, "").reference)] = (
                commit
            )
        return cls(
            tips,
            pull_requests.result(),
            remote.repository.full_name,
            frozenset({default_branch.result(), notes.branch.name}),
            DiscardedBranches.from_text(notes.read(NotesFile.DISCARDED_BRANCHES.value)),
        )


# %% the section


@dataclass(frozen=True)
class CleanupReminder(ReportSection):
    """
    How many branches are ready for deletion, and the command deleting them.
    """

    kept: KeptBranches
    """
    The repository's branches and pull requests.
    """

    def lines(self) -> list[ReportLine]:
        ready = self.kept.ready()
        if not ready:
            return []
        plural = "es" if len(ready) > 1 else ""
        command = WorkflowCommand.command_line(WorkflowCommand.CLEANUP)
        return [
            ReportLine(
                f"github-workflow: {len(ready)} branch{plural} ready for deletion: "
                f"run `{command}`",
                Tone.ACTION,
            )
        ]


# %% deleting them


class DeletionPlaceholder(StrEnum):
    """
    The names the deletion workflow template leaves to be filled in.
    """

    NOTES_BRANCH = "__NOTES_BRANCH__"
    """
    The notes branch, whose pushes run the workflow.
    """

    LIST_FILE = "__LIST_FILE__"
    """
    The file listing the branches to delete.
    """

    SCRIPT_FILE = "__SCRIPT_FILE__"
    """
    The script deleting them.
    """


@dataclass(frozen=True)
class BranchCleanup(WorkflowStep):
    """
    The branches ready for deletion deleted in one push, each only while still at the
    commit it was found at, and entered in the session log; those this session may not
    delete are listed on the notes branch with the workflow that deletes them when it
    is pushed.
    """

    git: GitCommandRunner
    """
    Runs git in the checkout.
    """

    remote: OwnedRemote
    """
    The owner's remote.
    """

    kept: KeptBranches
    """
    The repository's branches and pull requests.
    """

    notes: NotesBranch
    """
    The notes branch, which carries the list and the workflow when deletion is refused.
    """

    log: SessionLog
    """
    Where the deletions are entered.
    """

    def run(self) -> str:
        ready = self.kept.ready()
        if not ready:
            return "no branch is ready for deletion"
        refused = self.git.delete_remote_branches(
            self.remote.name, {branch: self.kept.tips[branch] for branch in ready}
        )
        deleted = len(ready) - len(refused)
        removed = {
            "deleted": [branch for branch in ready if branch not in refused],
            "handed to the deletion workflow": refused,
        }
        self.log.enter(
            "branches whose pull requests are closed or which were discarded: "
            + "; ".join(
                f"{what} {', '.join(f'`{branch}`' for branch in branches)}"
                for what, branches in removed.items()
                if branches
            )
        )
        if not refused:
            return f"deleted {deleted} branch{'es' if deleted > 1 else ''}"
        workflow = (
            WorkflowTemplate.DELETION_WORKFLOW.value.read_text()
            .replace(DeletionPlaceholder.NOTES_BRANCH, self.notes.branch.name)
            .replace(DeletionPlaceholder.LIST_FILE, str(NotesFile.READY_FOR_DELETION))
            .replace(DeletionPlaceholder.SCRIPT_FILE, str(NotesFile.DELETION_SCRIPT))
        )
        listed = BranchTips({branch: self.kept.tips[branch] for branch in refused})
        self.notes.fetch()
        self.notes.write(
            {
                NotesFile.READY_FOR_DELETION.value: listed.to_text(),
                NotesFile.DELETION_WORKFLOW.value: workflow,
                NotesFile.DELETION_SCRIPT.value: (
                    WorkflowTemplate.DELETION_SCRIPT.value.read_text()
                ),
            },
            f"List {len(refused)} branches for deletion",
        )
        return (
            f"deleted {deleted}; this session may not delete the other {len(refused)}, "
            f"so they are listed on {self.notes.branch.name}, whose Actions workflow "
            f"deletes them"
        )


# %% clones of somebody else's repositories


@dataclass(frozen=True)
class UnusedCloneRemoval(WorkflowStep):
    """
    The clones of somebody else's repositories that no session has made or fetched
    into for a while, removed, together with an owner's directory they leave empty.
    """

    clones: Path
    """
    The directory holding the clones, as ``<owner>/<name>``.
    """

    unused_for: timedelta = timedelta(weeks=1)
    """
    How long a clone goes unused before no running session is taken to read it.
    """

    def run(self) -> str:
        cutoff = time.time() - self.unused_for.total_seconds()
        unused = [
            clone
            for clone in sorted(self.clones.glob("*/*"))
            if self.last_used(clone) < cutoff
        ]
        for clone in unused:
            shutil.rmtree(clone)
            if not any(clone.parent.iterdir()):
                clone.parent.rmdir()
        if not unused:
            return "no clone of somebody else's repository is unused"
        plural = "s" if len(unused) > 1 else ""
        return (
            f"removed {len(unused)} clone{plural} of somebody else's repositories "
            f"unused for {self.unused_for.days} days"
        )

    @staticmethod
    def last_used(clone: Path) -> float:
        """
        :param clone: A clone of somebody else's repository.
        :return: When it was last made or fetched into, in seconds since the epoch.
        """
        fetched = GitCommandRunner(clone).repository_state_path(GitStateFile.FETCH_HEAD)
        return (fetched if fetched.exists() else fetched.parent).stat().st_mtime


# %% the command


@dataclass(frozen=True)
class Cleanup(WorkflowStep):
    """
    The branches ready for deletion deleted, and the clones of somebody else's
    repositories no session uses removed.
    """

    branches: BranchCleanup
    """
    Deletes the branches.
    """

    clones: UnusedCloneRemoval | None
    """
    Removes the clones, ``None`` when the plugin's data directory, which holds them, is
    not known.
    """

    def run(self) -> str:
        done = [self.branches.run()]
        if self.clones is not None:
            done.append(self.clones.run())
        return "; ".join(done)
