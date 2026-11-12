"""
Branches GitHub kept although their pull request is closed, and branches discarded as
thrown away: listed at session start, and deleted by the cleanup command or, where the
session may not delete branches, by an Actions workflow on the notes branch; and the
clones of somebody else's repositories no session uses any more, removed.
"""

from __future__ import annotations

import shutil
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Self

from domain_model.git.commands import GitCommandRunner
from domain_model.git.revisions import BranchName, BranchTip, CommitHash, TextFiles
from domain_model.github.repository_client import (
    GitHubRepository,
    PullRequestsFromForks,
)
from domain_model.github.rest_models import RestPullRequest
from domain_model.github.vocabulary import PullRequestState
from domain_model.locations import GitStateFile

from github_workflow.command_line import RunnableCommand
from github_workflow.exceptions import (
    DetachedHeadError,
    NothingToDiscardError,
    UndiscardableBranchError,
)
from github_workflow.locations import NotesFile
from github_workflow.notes.branch import NotesBranch
from github_workflow.policy import WritePolicy
from github_workflow.remotes import OwnedRemote
from github_workflow.report_lines import CountedThing, ReportLine, Speaker, Tone
from github_workflow.report_section import ReportSection
from github_workflow.work import PullRequestRetirement, SessionLog, WorkflowStep
from github_workflow.workflow_templates import DeletionPlaceholder, NotesBranchWorkflow

# %% branches listed with their commits


@dataclass(frozen=True)
class BranchTips:
    """
    Branches, each with the commit it may be deleted at, as the notes branch lists them.
    """

    tips: tuple[BranchTip, ...] = ()
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
        return cls(
            tuple(
                BranchTip(BranchName(branch), CommitHash(commit))
                for branch, commit in pairs
            )
        )

    def to_text(self) -> str:
        """:return: The list as the notes branch keeps it."""
        ordered = sorted(self.tips, key=lambda tip: tip.branch)
        return "".join(f"{tip.branch} {tip.commit}\n" for tip in ordered)

    def extended(self, tip: BranchTip) -> Self:
        """
        :param tip: Another branch, and its commit.
        :return: These branches and that one, in place of an earlier entry of its
            branch.
        """
        others = tuple(listed for listed in self.tips if listed.branch != tip.branch)
        return type(self)((*others, tip))


# %% discarded branches


@dataclass(frozen=True)
class DiscardedBranches(BranchTips):
    """
    The branches discarded as thrown away, each with the commit it was at when
    discarded.
    """


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

    name: BranchName | None = None
    """
    The branch to discard, the checked-out one when ``None``.
    """

    def run(self) -> str:
        checked_out = self.policy.checkout.working_tree.checked_out_branch()
        branch = self.name or (None if checked_out is None else checked_out.name)
        if branch is None:
            raise DetachedHeadError()
        if branch in {self.policy.default_branch, self.notes.branch.name}:
            raise UndiscardableBranchError(branch)
        tip = self.policy.remote.branch(branch).tip()
        if tip is None:
            raise NothingToDiscardError(branch)
        self.notes.fetch()
        listed = self.notes.read(NotesFile.DISCARDED_BRANCHES)
        discarded = DiscardedBranches.from_text(listed).extended(BranchTip(branch, tip))
        self.notes.write(
            TextFiles({NotesFile.DISCARDED_BRANCHES: discarded.to_text()}),
            f"Discard {branch}",
        )
        owner = self.policy.remote.repository.owner
        closed = [
            pull_request.number
            for pull_request in self.pull_requests.open_fork_branch_pull_requests(
                owner, branch
            )
        ]
        for number in closed:
            self.retirement.retire(
                number, f"Discarded: its branch {branch} is marked for deletion."
            )
        command = RunnableCommand.CLEANUP.usage()
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

    tips: Sequence[BranchTip]
    """
    Each branch on the repository, and the commit it is at.
    """

    pull_requests: Sequence[RestPullRequest]
    """
    Every pull request on the repository, open or closed.
    """

    repository: str
    """
    The repository's full name, which a pull request's head names when it is from this
    repository.
    """

    protected: frozenset[BranchName]
    """
    The branches never deleted: the default branch and the notes branch.
    """

    discarded: DiscardedBranches = field(default_factory=DiscardedBranches)
    """
    The branches discarded as thrown away.
    """

    def ready(self) -> list[BranchTip]:
        """
        :return: Each branch whose pull request is closed, or that was discarded, and
            that is still at the commit it was closed or discarded at, with no open pull
            request from or into it; never a protected one. Ordered by branch.
        """
        in_use: set[BranchName] = set()
        closed: set[BranchTip] = set()
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
                closed.add(BranchTip(head.branch, head.commit))
        ready = [
            tip
            for tip in self.tips
            if tip.branch not in self.protected
            and tip.branch not in in_use
            and (tip in closed or tip in self.discarded.tips)
        ]
        return sorted(ready, key=lambda tip: tip.branch)

    @classmethod
    def read(
        cls, remote: OwnedRemote, github: GitHubRepository, notes: NotesBranch
    ) -> KeptBranches:
        """
        :param remote: The owner's remote.
        :param github: The owner's repository on GitHub.
        :param notes: The notes branch, as last fetched.
        :return: The repository's branches and pull requests, read at once, and the
            branches the notes branch lists as discarded.
        """
        with ThreadPoolExecutor() as pool:
            tips = pool.submit(remote.branch_tips)
            pull_requests = pool.submit(github.all_pull_requests)
            default_branch = pool.submit(github.default_branch)
        return cls(
            tips.result(),
            pull_requests.result(),
            remote.repository.full_name,
            frozenset({default_branch.result(), notes.branch.name}),
            DiscardedBranches.from_text(notes.read(NotesFile.DISCARDED_BRANCHES)),
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
        branches = CountedThing.BRANCH.counted(len(ready))
        command = RunnableCommand.CLEANUP.usage()
        return [
            ReportLine(
                Speaker.WORKFLOW.says(
                    f"{branches} ready for deletion: run `{command}`"
                ),
                Tone.ACTION,
            )
        ]


# %% deleting them


@dataclass(frozen=True)
class BranchCleanup(WorkflowStep):
    """
    The branches ready for deletion deleted in one push, each only while still at the
    commit it was found at, and entered in the session log; those this session may not
    delete are listed on the notes branch with the workflow that deletes them when it is
    pushed.
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
        refused = self.remote.delete_branches(ready)
        deleted = len(ready) - len(refused)
        removed = {
            "deleted": [tip.branch for tip in ready if tip.branch not in refused],
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
            return f"deleted {CountedThing.BRANCH.counted(deleted)}"
        listed = BranchTips(tuple(tip for tip in ready if tip.branch in refused))
        workflow = NotesBranchWorkflow.DELETION.files(
            self.notes.branch.name,
            {DeletionPlaceholder.LIST_FILE: str(NotesFile.READY_FOR_DELETION)},
        )
        self.notes.fetch()
        self.notes.write(
            TextFiles({NotesFile.READY_FOR_DELETION: listed.to_text()}).combined(
                workflow
            ),
            f"List {CountedThing.BRANCH.counted(len(refused))} for deletion",
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
    The clones of somebody else's repositories that no session has made or fetched into
    for a while, removed, together with an owner's directory they leave empty.
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
        clones = CountedThing.CLONE.counted(len(unused))
        return (
            f"removed {clones} of somebody else's repositories unused for "
            f"{self.unused_for.days} days"
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
