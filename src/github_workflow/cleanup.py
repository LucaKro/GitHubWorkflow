"""
Branches GitHub kept although their pull request is closed: closed without merging, or
merged before GitHub deleted merged branches. Listed at session start, deleted by the
cleanup command - or, where the session may not delete branches, handed to an Actions
workflow on the notes branch.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import StrEnum

from basstler_domain_model.git.commands import GitCommandRunner, RemoteBranch
from basstler_domain_model.github.pull_request_fields import (
    PullRequestField,
    PullRequestHead,
    PullRequestPayload,
)
from basstler_domain_model.github.repository_client import GitHubRepository
from basstler_domain_model.github.vocabulary import IssueState

from github_workflow.command_line import WorkflowCommand
from github_workflow.hooks import ReportLine, Tone
from github_workflow.locations import NotesFile, WorkflowTemplate
from github_workflow.notes.branch import NotesBranch
from github_workflow.remotes import OwnedRemote
from github_workflow.report_section import ReportSection
from github_workflow.work import WorkflowStep

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

    pull_requests: Sequence[PullRequestPayload]
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

    def ready(self) -> list[str]:
        """
        :return: Each branch whose pull request is closed and that is still at the
            commit it was closed at, with no open pull request; never a protected one.
        """
        open_branches = set()
        closed_heads: dict[str, set[str]] = {}
        for record in self.pull_requests:
            number = PullRequestField.NUMBER.read(record)
            head = PullRequestHead.from_record(record, number)
            if head.repository != self.repository:
                continue
            if PullRequestField.STATE.read(record, number) == IssueState.OPEN:
                open_branches.add(head.branch)
            else:
                closed_heads.setdefault(head.branch, set()).add(head.commit)
        return sorted(
            branch
            for branch, tip in self.tips.items()
            if branch not in self.protected
            and branch not in open_branches
            and tip in closed_heads.get(branch, set())
        )

    @classmethod
    def read(
        cls,
        git: GitCommandRunner,
        remote: OwnedRemote,
        github: GitHubRepository,
        notes_branch: str,
    ) -> KeptBranches:
        """
        :param git: Runs git in the checkout.
        :param remote: The owner's remote.
        :param github: The owner's repository on GitHub.
        :param notes_branch: The branch the notes live on.
        :return: The repository's branches and pull requests, read at once.
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
            frozenset({default_branch.result(), notes_branch}),
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


@dataclass(frozen=True)
class BranchCleanup(WorkflowStep):
    """
    The branches ready for deletion deleted; those this session may not delete are
    listed on the notes branch with the workflow that deletes them when it is pushed.
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

    def run(self) -> str:
        ready = self.kept.ready()
        if not ready:
            return "no branch is ready for deletion"
        refused = [
            branch
            for branch in ready
            if not self.git.delete_remote_branch(
                RemoteBranch(self.remote.name, branch)
            ).succeeded
        ]
        deleted = len(ready) - len(refused)
        if not refused:
            return f"deleted {deleted} branch{'es' if deleted > 1 else ''}"
        workflow = (
            WorkflowTemplate.DELETION_WORKFLOW.value.read_text()
            .replace(DeletionPlaceholder.NOTES_BRANCH, self.notes.branch.name)
            .replace(DeletionPlaceholder.LIST_FILE, str(NotesFile.READY_FOR_DELETION))
        )
        self.notes.fetch()
        self.notes.write(
            {
                NotesFile.READY_FOR_DELETION.value: "\n".join(refused) + "\n",
                NotesFile.DELETION_WORKFLOW.value: workflow,
            },
            f"List {len(refused)} branches for deletion",
        )
        return (
            f"deleted {deleted}; this session may not delete the other {len(refused)}, "
            f"so they are listed on {self.notes.branch.name}, whose Actions workflow "
            f"deletes them"
        )
