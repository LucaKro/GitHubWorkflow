"""
The writes a session makes to git and GitHub, each one step that checks the
:class:`WritePolicy` before it writes anything and reports what it did in one line.
"""

from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from basstler_domain_model.git.branch_tips import BranchTip
from basstler_domain_model.git.commands import (
    GitCommandRunner,
    ProposedPush,
    RemoteBranch,
)
from basstler_domain_model.git.conflict_markers import ConflictMarker
from basstler_domain_model.github.closing_lines import ClosingLines
from basstler_domain_model.github.number_links import NumberLink
from basstler_domain_model.github.repository_client import (
    IssueBoard,
    IssueTracker,
    PullRequestOpener,
    PullRequestReader,
    PullRequestsFromForks,
    PullRequestWriter,
    RepositoryDetails,
    StackReader,
)
from basstler_domain_model.github.stack_placement import StackPlacement
from basstler_domain_model.github.vocabulary import PullRequestState
from basstler_domain_model.repository import GitHubAddress, Repository

from github_workflow.checkout import ProjectCheckout
from github_workflow.command_line import RunnableCommand
from github_workflow.exceptions import (
    BranchDeletedFromGitHubError,
    BranchNotPushedError,
    ConflictMarkersLeftError,
    DetachedHeadError,
    DraftUnfinishedError,
    MergeConflictError,
    NoMergeInProgressError,
    NothingToDescribeError,
    PullRequestNotOpenError,
    PushRefusedError,
    StackedBranchMergeError,
    UnbuildablePullRequestError,
    UnpushedCommitsError,
    UnreplaceablePullRequestError,
    UnresolvedConflictError,
)
from github_workflow.labels import IssueLabel
from github_workflow.notes.saving import NotesSave
from github_workflow.policy import WritePolicy
from github_workflow.push_hook import PushHook
from github_workflow.settings import WorkflowSettings

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
    Switching to an existing branch, the checkout's or one only the owner's remote has.
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
        git = self.policy.checkout.git
        git.fetch_branch(RemoteBranch(self.policy.remote.name, self.name))
        git.switch_to(self.name)
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
        """
        :raises MergeInProgressError: If a merge is in progress.
        """
        branch = self.policy.work_branch()
        self.policy.refuse_while_merging(branch)
        commit = self.policy.checkout.git.commit(
            self.policy.commit_message(self.message), self.paths
        )
        return f"committed {BranchTip.abbreviated(commit)} on {branch}"


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
        """
        :raises MergeInProgressError: If a merge is in progress.
        """
        branch = RemoteBranch(self.policy.remote.name, self.policy.work_branch())
        self.policy.refuse_while_merging(branch.name)
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
    What the description of a pull request onto the default branch ends with, given its
    branch.
    """

    @abstractmethod
    def appended_to(self, body: str, branch: str) -> str:
        """
        :param body: A pull request's description, which may end with it already.
        :param branch: The pull request's branch.
        :return: The description, ending with it once.
        """


class PullRequestRetirement(ABC):
    """
    An open pull request of the owner's that a session no longer needs, closed and
    marked as closed by a session, with why.
    """

    @abstractmethod
    def retire(self, number: int, reason: str) -> None:
        """
        :param number: The pull request.
        :param reason: Why it is closed, commented on it.
        """


class SessionLog(ABC):
    """
    Where what a session does without asking is entered, for the person to read in one
    place.
    """

    @abstractmethod
    def enter(self, action: str) -> None:
        """
        :param action: What the session did, in one line, naming the issues, pull
            requests and branches it touched.
        """


@dataclass(frozen=True)
class Replacement:
    """
    The pull request a new draft replaces, closed once the draft is open.
    """

    number: int
    """
    The pull request replaced.
    """

    retirement: PullRequestRetirement
    """
    Closes it.
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

    issue_labels: PullRequestOpenedLabelling
    """
    Labels the issues its description closes.
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

    replacement: Replacement | None = None
    """
    The pull request the draft replaces, ``None`` for none.
    """

    def run(self) -> str:
        """
        :raises UnreplaceablePullRequestError: If the pull request to replace is not
            open, is on another repository, or is the work branch's own.
        :raises StackContinuesAboveError: If other open pull requests already sit on
            the one to stack on; nothing is opened then.
        :raises DraftUnfinishedError: If closing the replaced pull request, labelling
            the issues or stacking the draft fails once it is opened.
        """
        branch = RemoteBranch(self.policy.remote.name, self.policy.work_branch())
        if not self.policy.checkout.git.has_remote_branch(branch):
            raise BranchNotPushedError(branch.name)
        if self.replacement is not None:
            self.check_replaceable(self.replacement.number, branch.name)
        if self.below is not None:
            self.placement.check_placeable(self.below)
        base = (
            self.policy.default_branch
            if self.below is None
            else self.placement.host.pull_request(self.below).head.branch
        )
        body = (
            self.ending.appended_to(self.body, branch.name)
            if self.ending is not None and self.below is None
            else self.body
        )
        number = self.opener.open_draft(branch.name, base, self.title, body)
        try:
            return self.finish(number, branch.name, base, body)
        except Exception as raised:
            raise DraftUnfinishedError(number, str(raised)) from raised

    def finish(self, number: int, branch: str, base: str, body: str) -> str:
        """
        Close the pull request the opened draft replaces, label the issues the draft
        closes, and stack it, where asked to.

        :param number: The opened draft.
        :param branch: The work branch it was opened from.
        :param base: The branch it targets.
        :param body: Its description.
        :return: What was done.
        """
        link = NumberLink(number, self.policy.remote.repository.issue_url(number))
        opened = f"opened draft {link.markdown()}: {branch} onto {base}"
        if self.replacement is not None:
            replaced = self.replacement.number
            self.replacement.retirement.retire(replaced, f"Replaced by #{number}.")
            opened += f"; closed #{replaced}, which it replaces: tell the person"
        labelled = self.issue_labels.label(body)
        if labelled:
            named = ", ".join(f"#{issue}" for issue in labelled)
            opened += f"; labelled {named} {IssueLabel.PULL_REQUEST_OPENED}"
        if self.below is None:
            return opened
        stack = self.placement.place(self.below, number)
        return f"{opened}, in stack {stack.number}"

    def check_replaceable(self, number: int, branch: str) -> None:
        """
        :param number: The pull request to replace.
        :param branch: The work branch the draft is opened from.
        :raises UnreplaceablePullRequestError: If it is not open, is on another
            repository, or is the work branch's own.
        """
        replaced = self.placement.host.pull_request(number)
        repository = self.policy.remote.repository.full_name
        if replaced.state is not PullRequestState.OPEN:
            raise UnreplaceablePullRequestError(number, f"it is {replaced.state}")
        if replaced.head.repository != repository:
            raise UnreplaceablePullRequestError(
                number, f"its branch is not on {repository}"
            )
        if replaced.head.branch == branch:
            raise UnreplaceablePullRequestError(
                number, "it is this branch's own: rewrite it with `describe` instead"
            )


@dataclass(frozen=True)
class PullRequestOpenedLabelling:
    """
    :attr:`IssueLabel.PULL_REQUEST_OPENED` on the issues a pull request's description
    closes, put on when it opens and taken off when it is closed unmerged.
    """

    issues: IssueTracker
    """
    The issues, and the labels they are given.
    """

    def label(self, description: str) -> list[int]:
        """
        :param description: The opened pull request's description.
        :return: The issues it closes, now labelled.
        """
        issues = ClosingLines(description).issues()
        if not issues:
            return []
        self.issues.create_missing_labels([IssueLabel.PULL_REQUEST_OPENED])
        for issue in issues:
            self.issues.add_labels(issue, [IssueLabel.PULL_REQUEST_OPENED])
        return issues

    def unlabel(self, description: str) -> list[int]:
        """
        :param description: The description of a pull request closed unmerged.
        :return: The issues it closes that carried the label, no longer labelled.
        """
        carrying = [
            issue
            for issue in ClosingLines(description).issues()
            if IssueLabel.PULL_REQUEST_OPENED in self.issues.issue(issue).labels
        ]
        for issue in carrying:
            self.issues.remove_label(issue, IssueLabel.PULL_REQUEST_OPENED)
        return carrying


@dataclass(frozen=True)
class DescriptionRewrite(WorkflowStep):
    """
    A new description, title or both for an open pull request on the owner's repository,
    a draft or ready for review, so it follows the pushed commits; a closed or merged
    one keeps its own. A new description keeps the lines of the old one that close an
    issue, and one onto the default branch ends as a draft's does.

    :raises NothingToDescribeError: If neither is given.
    :raises PullRequestNotOpenError: If the pull request is not open.
    """

    pull_requests: PullRequestReader
    """
    Reads the pull request.
    """

    writer: PullRequestWriter
    """
    Writes its description.
    """

    titles: IssueBoard
    """
    Writes its title, a pull request being an issue to GitHub too.
    """

    repository: RepositoryDetails
    """
    Reads the repository's default branch.
    """

    number: int
    """
    The pull request.
    """

    body: str | None
    """
    The new description, ``None`` to keep the old one.
    """

    title: str | None = None
    """
    The new title, ``None`` to keep the old one.
    """

    ending: DescriptionEnding | None = None
    """
    What the new description of a pull request onto the default branch ends with,
    ``None`` for nothing.
    """

    def run(self) -> str:
        if self.body is None and self.title is None:
            raise NothingToDescribeError(self.number)
        pull_request = self.pull_requests.pull_request(self.number)
        if pull_request.state is not PullRequestState.OPEN:
            raise PullRequestNotOpenError(self.number)
        rewritten = []
        if self.body is not None:
            kept = ClosingLines(pull_request.body or "").kept_in(self.body)
            onto_default = pull_request.base == self.repository.default_branch()
            body = (
                self.ending.appended_to(kept, pull_request.head.branch)
                if self.ending is not None and onto_default
                else kept
            )
            self.writer.set_description(self.number, body)
            rewritten.append("description")
        if self.title is not None:
            self.titles.set_issue_title(self.number, self.title)
            rewritten.append("title")
        return f"rewrote the {' and '.join(rewritten)} of #{self.number}"


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

    pull_requests: PullRequestsFromForks
    """
    The owner's repository, whose pull requests from a branch show it was on GitHub.
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
        if self.policy.checkout.git.fetched_or_pushed(branch.tracking_reference):
            return True
        owner = self.policy.remote.repository.owner
        return bool(self.pull_requests.pull_requests_from(owner, branch.name))


# %% taking in the default branch


@dataclass(frozen=True)
class WorkBranchMerge:
    """
    A branch as GitHub has it merged into the checked-out work branch, committed as the
    person, never forced; a conflicting merge is left in progress, its files named, for
    :class:`MergeCompletion` or :class:`MergeAbort` to end.
    """

    policy: WritePolicy
    """
    The checkout and its work branch.
    """

    def merge(self, merged: RemoteBranch, described: str) -> str:
        """
        :param merged: The branch to merge.
        :param described: How the report names it.
        :return: What was merged, or that nothing had to be.
        :raises DefaultBranchWriteError: If the default branch is checked out.
        :raises MergeInProgressError: If a merge is in progress already.
        :raises MergeConflictError: If the merge conflicts.
        """
        branch = self.policy.work_branch()
        git = self.policy.checkout.git
        self.policy.refuse_while_merging(branch)
        git.fetch_branch(merged).raise_if_failed()
        if git.contains(merged.tracking_reference, "HEAD"):
            return f"{branch} has {described}'s commits already"
        result = git.merge(
            merged.tracking_reference,
            self.policy.commit_message(f"Merge {described} into {branch}"),
        )
        if not result.succeeded:
            conflicted = git.conflicted_files()
            if not conflicted:
                result.raise_if_failed()
            raise MergeConflictError(branch, described, tuple(conflicted))
        push = RunnableCommand.PUSH.usage()
        return f"merged {described} into {branch}; push it with `{push}`"


@dataclass(frozen=True)
class MergeCompletion(WorkflowStep):
    """
    The merge in progress on the work branch committed as the person, once the files it
    left conflicting hold their resolved content.

    :raises DefaultBranchWriteError: If the default branch is checked out.
    :raises NoMergeInProgressError: If no merge is in progress.
    :raises ConflictMarkersLeftError: If a resolved file still marks a conflict.
    :raises UnresolvedConflictError: If a file the merge left conflicting is not among
        the resolved ones.
    """

    policy: WritePolicy
    """
    The checkout, its work branch and who commits.
    """

    resolved: Sequence[Path]
    """
    The files resolved, as they are in the working tree.
    """

    def run(self) -> str:
        branch = self.policy.work_branch()
        git = self.policy.checkout.git
        if not git.merge_in_progress():
            raise NoMergeInProgressError(branch)
        marked = [
            str(path)
            for path in self.resolved
            if ConflictMarker.left_in((git.working_directory / path).read_text())
        ]
        if marked:
            raise ConflictMarkersLeftError(tuple(marked))
        git.stage(self.resolved)
        unresolved = git.conflicted_files()
        if unresolved:
            raise UnresolvedConflictError(tuple(unresolved))
        commit = git.commit_staged(self.policy.commit_message(git.merge_message()))
        push = RunnableCommand.PUSH.usage()
        return (
            f"committed the merge {BranchTip.abbreviated(commit)} on {branch}; push it "
            f"with `{push}`"
        )


@dataclass(frozen=True)
class MergeAbort(WorkflowStep):
    """
    The merge in progress on the work branch undone, its commit and files as before.

    :raises DefaultBranchWriteError: If the default branch is checked out.
    :raises NoMergeInProgressError: If no merge is in progress.
    """

    policy: WritePolicy
    """
    The checkout and its work branch.
    """

    def run(self) -> str:
        branch = self.policy.work_branch()
        git = self.policy.checkout.git
        if not git.merge_in_progress():
            raise NoMergeInProgressError(branch)
        git.abort_merge()
        return f"undid the merge on {branch}; it is as it was before"


@dataclass(frozen=True)
class BaseMerge(WorkflowStep):
    """
    GitHub's default branch merged into the checked-out work branch: one whose pull
    request targets the default branch, the bottom of a stack included.

    :raises DefaultBranchWriteError: If the default branch is checked out.
    :raises StackedBranchMergeError: If the branch's pull request sits higher in a
        stack, targeting the branch below it.
    :raises MergeConflictError: If the merge conflicts.
    """

    policy: WritePolicy
    """
    The checkout, its work branch and the default branch.
    """

    pull_requests: PullRequestsFromForks
    """
    Finds the pull requests opened from the work branch.
    """

    stacks: StackReader
    """
    Reads whether one is in a stack.
    """

    def run(self) -> str:
        branch = self.policy.work_branch()
        owner = self.policy.remote.repository.owner
        for pull_request in self.pull_requests.pull_requests_from(owner, branch):
            stacked = self.stacks.stack_of(pull_request.number) is not None
            above = pull_request.base != self.policy.default_branch
            if pull_request.state is PullRequestState.OPEN and stacked and above:
                raise StackedBranchMergeError(branch, pull_request.number)
        default = RemoteBranch(self.policy.remote.name, self.policy.default_branch)
        return WorkBranchMerge(self.policy).merge(default, default.name)


@dataclass(frozen=True)
class OpenPullRequestBranch:
    """
    The branch of an open pull request on the owner's repository, which work builds on
    or a finding's test runs on.
    """

    pull_requests: PullRequestReader
    """
    Reads the pull request.
    """

    repository: Repository
    """
    The owner's repository, which the branch has to be on.
    """

    def branch(self, number: int) -> str:
        """
        :param number: The pull request.
        :return: Its branch.
        :raises UnbuildablePullRequestError: If it is not open, or its branch is on
            another repository.
        """
        pull_request = self.pull_requests.pull_request(number)
        if pull_request.state is not PullRequestState.OPEN:
            raise UnbuildablePullRequestError(number, f"it is {pull_request.state}")
        if pull_request.head.repository != self.repository.full_name:
            raise UnbuildablePullRequestError(
                number,
                f"its branch is on {pull_request.head.repository or 'no repository'}, "
                f"not on {self.repository.full_name}",
            )
        return pull_request.head.branch


@dataclass(frozen=True)
class PullRequestMerge(WorkflowStep):
    """
    The branch of another open pull request on the owner's repository merged into the
    checked-out work branch, so the work builds on it before it reaches the default
    branch.

    :raises DefaultBranchWriteError: If the default branch is checked out.
    :raises UnbuildablePullRequestError: If the pull request is not open, or its branch
        is on another repository.
    :raises MergeConflictError: If the merge conflicts.
    """

    policy: WritePolicy
    """
    The checkout, its work branch and the owner's remote.
    """

    pull_requests: PullRequestReader
    """
    Reads the pull request.
    """

    number: int
    """
    The pull request to build on.
    """

    def run(self) -> str:
        self.policy.work_branch()
        branch = OpenPullRequestBranch(
            self.pull_requests, self.policy.remote.repository
        ).branch(self.number)
        merged = RemoteBranch(self.policy.remote.name, branch)
        described = f"#{self.number}'s branch {branch}"
        return WorkBranchMerge(self.policy).merge(merged, described)


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
        """
        Unlike :meth:`WorkflowStep.run`, writes nothing when the repository was cloned
        there before: that clone is reused as it is.
        """
        destination = self.directory / self.repository.name
        if destination.exists():
            return (
                f"{self.repository} is already cloned into {destination}; fetch there "
                f"for what changed since"
            )
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
