"""
The errors the workflow's commands end in.
"""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass
from typing import TYPE_CHECKING

from domain_model.exceptions import DataclassException
from domain_model.git.revisions import BranchName

from github_workflow.command_line import CommandOption, RunnableCommand

if TYPE_CHECKING:
    from domain_model.code_version import CodeVersion
    from domain_model.git.remotes import Remote
    from domain_model.git.revisions import BranchTip
    from domain_model.github.vocabulary import WorkflowRunConclusion
    from domain_model.repository import Repository

    from github_workflow.findings import FindingStage

# %% whose repository


@dataclass
class NoOwnedRemoteError(DataclassException, LookupError):
    """
    Raised when no remote of the checkout points at a repository the owner owns.
    """

    owner: str
    """
    The account whose repositories alone are written to.
    """

    remote_names: tuple[str, ...]
    """
    Every remote the checkout has.
    """

    def error_message(self) -> str:
        remotes = ", ".join(self.remote_names) or "none"
        return f"no remote points at a repository of {self.owner} (remotes: {remotes})"

    def suggest_correction(self) -> str:
        return f"Add a remote for {self.owner}'s fork or repository, and work there."


@dataclass
class AmbiguousOwnedRemoteError(DataclassException, LookupError):
    """
    Raised when several remotes point at the owner's repositories and none is
    ``origin``.
    """

    owner: str
    """
    The account whose repositories alone are written to.
    """

    remote_names: tuple[str, ...]
    """
    The remotes that point at the owner's repositories.
    """

    def error_message(self) -> str:
        return (
            f"several remotes point at {self.owner}'s repositories "
            f"({', '.join(self.remote_names)}) and none is origin"
        )

    def suggest_correction(self) -> str:
        return "Rename the one to work with to origin."


@dataclass
class ForcedPushError(DataclassException, PermissionError):
    """
    Raised when a push from a Claude Code session would drop commits the remote's branch
    has.
    """

    reference: str
    """
    The remote's reference the push overwrites.
    """

    def error_message(self) -> str:
        return (
            f"the push overwrites commits {self.reference} has: nothing is force-pushed"
        )

    def suggest_correction(self) -> str:
        return (
            f"Bring the branch up to date with `{RunnableCommand.SYNC.usage()}`, then "
            f"push with `{RunnableCommand.PUSH.usage()}`."
        )


@dataclass
class ForeignPushError(DataclassException, PermissionError):
    """
    Raised when a push from a Claude Code session goes to a repository the owner does
    not own.
    """

    url: str
    """
    The URL the push goes to.
    """

    owner: str
    """
    The account whose repositories alone are pushed to.
    """

    def error_message(self) -> str:
        return f"{self.url} is no repository of {self.owner}'s, so the push is refused"

    def suggest_correction(self) -> str:
        return f"Push only to {self.owner}'s repositories, through the workflow's push."


@dataclass
class UnknownDefaultBranchError(DataclassException, LookupError):
    """
    Raised when a push from a Claude Code session goes to a remote whose default branch
    cannot be read, so whether it changes that branch cannot be told.
    """

    remote: str
    """
    The remote pushed to.
    """

    def error_message(self) -> str:
        return f"the default branch of {self.remote} cannot be read, so the push is refused"

    def suggest_correction(self) -> str:
        return "Check that the remote can be reached and that it has a default branch."


# %% writing on a work branch


@dataclass
class DetachedHeadError(DataclassException, RuntimeError):
    """
    Raised when a write needs a work branch and none is checked out.
    """

    def error_message(self) -> str:
        return "no branch is checked out"

    def suggest_correction(self) -> str:
        return "Start a work branch or switch to one first."


@dataclass
class DefaultBranchWriteError(DataclassException, RuntimeError):
    """
    Raised when a commit or push would land on the default branch, which only pull
    requests may change.
    """

    branch: BranchName
    """
    The default branch.
    """

    def error_message(self) -> str:
        return f"{self.branch} is the default branch; work reaches it only through pull requests"

    def suggest_correction(self) -> str:
        return "Start a work branch and commit there."


@dataclass
class AssistantCreditError(DataclassException, ValueError):
    """
    Raised when a commit would credit an assistant as its author or co-author.
    """

    credit: str
    """
    The author or trailer line that credits it.
    """

    def error_message(self) -> str:
        return f"a commit may not credit an assistant: {self.credit}"

    def suggest_correction(self) -> str:
        return "Author the commit as the person running the tool, without the trailer."


@dataclass
class PushRefusedError(DataclassException, RuntimeError):
    """
    Raised when the remote refuses a push, which is never forced.
    """

    branch: BranchName
    """
    The branch that was pushed.
    """

    detail: str
    """
    What git said.
    """

    def error_message(self) -> str:
        return f"pushing {self.branch} was refused: {self.detail}"

    def suggest_correction(self) -> str:
        return "Sync the branch first; a push never overwrites what GitHub holds."


@dataclass
class BranchNotPushedError(DataclassException, RuntimeError):
    """
    Raised when a pull request is asked for a branch GitHub does not have.
    """

    branch: BranchName
    """
    The branch.
    """

    def error_message(self) -> str:
        return f"{self.branch} is not on GitHub"

    def suggest_correction(self) -> str:
        return "Push it first."


@dataclass
class UnpushedCommitsError(DataclassException, RuntimeError):
    """
    Raised when a branch and GitHub's copy of it both have commits the other lacks, and
    the local ones were never pushed.
    """

    branch: BranchName
    """
    The branch.
    """

    def error_message(self) -> str:
        return (
            f"{self.branch} has commits GitHub lacks, and GitHub has commits it lacks"
        )

    def suggest_correction(self) -> str:
        return "Ask the person running the tool how to bring the two together."


@dataclass
class MergeConflictError(DataclassException, ValueError):
    """
    Raised when merging a branch into a work branch conflicts; the merge is left in
    progress.
    """

    branch: BranchName
    """
    The work branch.
    """

    merged_branch: BranchName
    """
    The branch merged into it, as the report names it.
    """

    files: tuple[str, ...]
    """
    The files the merge left conflicting.
    """

    def error_message(self) -> str:
        return (
            f"merging {self.merged_branch} into {self.branch} conflicts in "
            f"{', '.join(self.files)}; the merge is in progress"
        )

    def suggest_correction(self) -> str:
        resolved = RunnableCommand.SYNC.usage(
            CommandOption.CONTINUE,
            values={CommandOption.CONTINUE: " ".join(self.files)},
        )
        abort = RunnableCommand.SYNC.usage(CommandOption.ABORT)
        return (
            "Edit those files to their resolved content, keeping both sides' intent and "
            f"no conflict markers, then run `{resolved}`. To give up instead, run "
            f"`{abort}`, which leaves the branch as it was."
        )


@dataclass
class MergeInProgressError(DataclassException, RuntimeError):
    """
    Raised when the work branch is committed to, pushed or merged into while a merge is
    in progress on it.
    """

    branch: BranchName
    """
    The work branch.
    """

    def error_message(self) -> str:
        return f"a merge is in progress on {self.branch}"

    def suggest_correction(self) -> str:
        resolved = RunnableCommand.SYNC.usage(CommandOption.CONTINUE)
        abort = RunnableCommand.SYNC.usage(CommandOption.ABORT)
        return f"Finish it with `{resolved}`, or undo it with `{abort}`."


@dataclass
class NoMergeInProgressError(DataclassException, RuntimeError):
    """
    Raised when a merge is to be finished or undone and none is in progress.
    """

    branch: BranchName
    """
    The work branch.
    """

    def error_message(self) -> str:
        return f"no merge is in progress on {self.branch}"

    def suggest_correction(self) -> str:
        base = RunnableCommand.SYNC.usage(CommandOption.BASE)
        stacked = RunnableCommand.SYNC.usage(CommandOption.ON)
        return f"Start one with `{base}` or `{stacked}`."


@dataclass
class ConflictMarkersLeftError(DataclassException, ValueError):
    """
    Raised when a file given as resolved still marks a conflict.
    """

    files: tuple[str, ...]
    """
    The files still marking one.
    """

    def error_message(self) -> str:
        return f"{', '.join(self.files)} still mark a conflict; nothing was committed"

    def suggest_correction(self) -> str:
        return (
            "Resolve every conflict in them, removing the markers, then run it again."
        )


@dataclass
class UnresolvedConflictError(DataclassException, ValueError):
    """
    Raised when a merge is to be finished while files it left conflicting are not
    resolved.
    """

    files: tuple[str, ...]
    """
    The files still conflicting.
    """

    def error_message(self) -> str:
        return f"{', '.join(self.files)} still conflict; nothing was committed"

    def suggest_correction(self) -> str:
        return "Resolve them too, and name them among the resolved files."


@dataclass
class UnbuildablePullRequestError(DataclassException, ValueError):
    """
    Raised when a work branch is to build on a pull request whose branch cannot be
    merged into it.
    """

    number: int
    """
    The pull request.
    """

    reason: str
    """
    Why its branch cannot be merged.
    """

    def error_message(self) -> str:
        return f"cannot build on #{self.number}: {self.reason}"

    def suggest_correction(self) -> str:
        return "Build on an open pull request whose branch is on the same repository."


@dataclass
class UnreplaceablePullRequestError(DataclassException, ValueError):
    """
    Raised when a new draft is to replace a pull request a session may not close.
    """

    number: int
    """
    The pull request.
    """

    reason: str
    """
    Why it cannot be replaced.
    """

    def error_message(self) -> str:
        return f"cannot replace #{self.number}: {self.reason}; nothing was opened"

    def suggest_correction(self) -> str:
        return (
            "Replace only an open pull request from another work branch on the owner's "
            "repository, or leave it to the person running the tool."
        )


@dataclass
class DraftUnfinishedError(DataclassException, RuntimeError):
    """
    Raised when a step after opening a draft fails, leaving the draft open.
    """

    number: int
    """
    The draft that was opened.
    """

    failure: str
    """
    What failed after it was opened.
    """

    def error_message(self) -> str:
        return f"opened draft #{self.number}, but then: {self.failure}"

    def suggest_correction(self) -> str:
        return (
            f"Do not open it again: #{self.number} stays open. Tell the person what "
            "failed."
        )


@dataclass
class StackedBranchMergeError(DataclassException, ValueError):
    """
    Raised when the default branch is to be merged into a branch whose pull request sits
    higher in a stack, targeting the branch below it.
    """

    branch: BranchName
    """
    The work branch.
    """

    pull_request: int
    """
    Its pull request, in a stack.
    """

    def error_message(self) -> str:
        return (
            f"{self.branch}'s pull request #{self.pull_request} sits higher in a stack"
        )

    def suggest_correction(self) -> str:
        stacked = RunnableCommand.SYNC.usage(CommandOption.ON)
        return (
            "Merge the default branch into the stack's bottom pull request, and its "
            f"branch into this one with `{stacked}`; or use GitHub's Rebase stack."
        )


@dataclass
class BranchDeletedFromGitHubError(DataclassException, LookupError):
    """
    Raised when a branch that was on GitHub is no longer there, as after its pull
    request was merged.
    """

    branch: BranchName
    """
    The branch.
    """

    def error_message(self) -> str:
        return f"{self.branch} was on GitHub and has been deleted there"

    def suggest_correction(self) -> str:
        return (
            "Do not push it again; ask the person running the tool whether its work "
            "is finished."
        )


# %% the checkout


@dataclass
class NotACheckoutError(DataclassException, RuntimeError):
    """
    Raised when a command that works on a checkout runs outside one.
    """

    directory: str
    """
    Where it ran.
    """

    def error_message(self) -> str:
        return f"{self.directory} is not inside a git checkout"

    def suggest_correction(self) -> str:
        return "Run the command inside the checkout it is to work on."


# %% pull requests


@dataclass
class PullRequestNotOpenError(DataclassException, RuntimeError):
    """
    Raised when a pull request to be rewritten is closed or merged.
    """

    number: int
    """
    The pull request.
    """

    def error_message(self) -> str:
        return f"#{self.number} is not an open pull request"

    def suggest_correction(self) -> str:
        return "Rewrite an open pull request; a closed or merged one keeps its own."


@dataclass
class ForeignPullRequestError(DataclassException, PermissionError):
    """
    Raised when a pull request to be rewritten was opened from somebody else's
    repository.
    """

    number: int
    """
    The pull request.
    """

    head_repository: str | None
    """
    The repository its branch lives in, ``None`` once that was deleted.
    """

    def error_message(self) -> str:
        source = self.head_repository or "a deleted repository"
        return f"#{self.number} was opened from {source}, not from the owner's"

    def suggest_correction(self) -> str:
        return (
            "Rewrite only a pull request of the owner's; ask its author for this one."
        )


@dataclass
class NoOpenPullRequestError(DataclassException, LookupError):
    """
    Raised when the work branch has no open pull request to write to.
    """

    branch: BranchName
    """
    The work branch.
    """

    def error_message(self) -> str:
        return f"{self.branch} has no open pull request"

    def suggest_correction(self) -> str:
        return "Open its draft first."


@dataclass
class NothingToLabelError(DataclassException, ValueError):
    """
    Raised when a pull request is to be labelled with no label to add or remove.
    """

    branch: BranchName
    """
    The work branch.
    """

    def error_message(self) -> str:
        return f"labelling {self.branch}'s pull request was given no label"

    def suggest_correction(self) -> str:
        return (
            f"Name a label to add with {CommandOption.ADD}, or to remove with "
            f"{CommandOption.REMOVE}."
        )


@dataclass
class PersonOnlyLabelError(DataclassException, PermissionError):
    """
    Raised when a session is to add or remove a label only the person sets.
    """

    label: str
    """
    The label.
    """

    def error_message(self) -> str:
        return f"{self.label} is set and removed only by the person running the tool"

    def suggest_correction(self) -> str:
        return "Leave it to the person."


@dataclass
class UnknownLabelError(DataclassException, LookupError):
    """
    Raised when a label to add is not one of the repository's.
    """

    labels: tuple[str, ...]
    """
    The labels the repository lacks.
    """

    def error_message(self) -> str:
        return f"the repository has no label {', '.join(self.labels)}"

    def suggest_correction(self) -> str:
        return "Use a label the repository has; creating one is the person's to do."


@dataclass
class ReviewThreadNotFoundError(DataclassException, LookupError):
    """
    Raised when a pull request has no review thread holding the comment named.
    """

    number: int
    """
    The pull request.
    """

    comment: int
    """
    The comment named.
    """

    def error_message(self) -> str:
        return f"#{self.number} has no review thread with comment {self.comment}"

    def suggest_correction(self) -> str:
        return "List the threads with `review list` to see their identifiers."


@dataclass
class UnpushedWorkError(DataclassException, RuntimeError):
    """
    Raised when a review thread is to be resolved while the work branch has commits
    GitHub's copy lacks.
    """

    branch: BranchName
    """
    The work branch.
    """

    def error_message(self) -> str:
        return f"{self.branch} has commits GitHub's copy lacks"

    def suggest_correction(self) -> str:
        return "Push the fix first, so the thread is resolved by what reviewers see."


@dataclass
class NothingToDescribeError(DataclassException, ValueError):
    """
    Raised when a pull request is to be rewritten with neither a new description nor a
    new title.
    """

    number: int
    """
    The pull request.
    """

    def error_message(self) -> str:
        return f"rewriting #{self.number} was given nothing to change"

    def suggest_correction(self) -> str:
        return "Give a new description, a new title, or both."


# %% discarding branches


@dataclass
class UndiscardableBranchError(DataclassException, ValueError):
    """
    Raised when the branch to discard is the default branch or the notes branch, which
    are never deleted.
    """

    branch: BranchName
    """
    The branch.
    """

    def error_message(self) -> str:
        return f"{self.branch} is never deleted, so it cannot be discarded"

    def suggest_correction(self) -> str:
        return "Name the work branch to discard."


@dataclass
class NothingToDiscardError(DataclassException, LookupError):
    """
    Raised when the branch to discard is not on GitHub, so there is nothing to delete.
    """

    branch: BranchName
    """
    The branch.
    """

    def error_message(self) -> str:
        return f"{self.branch} is not on GitHub, so there is nothing to delete"

    def suggest_correction(self) -> str:
        return "Only a branch on GitHub is discarded; leave this one as it is."


# %% text for GitHub


@dataclass
class WorkflowMarkerError(DataclassException, ValueError):
    """
    Raised when text a session gives a command for GitHub carries a comment in the form
    the workflow marks its own records with, such as a proof.
    """

    argument: str
    """
    The argument carrying it.
    """

    def error_message(self) -> str:
        return (
            f"{self.argument} carries a comment marking one of the workflow's records"
        )

    def suggest_correction(self) -> str:
        return "Leave the comment out; only the workflow writes its records."


# %% findings


@dataclass
class NotAFindingError(DataclassException, LookupError):
    """
    Raised when a finding to be accepted, shelved, rejected, proven, marked unproven,
    edited or commented on is none, or not in a stage that allows it.
    """

    number: int
    """
    The issue asked for.
    """

    def error_message(self) -> str:
        return f"#{self.number} is no finding that can be changed this way"

    def suggest_correction(self) -> str:
        return "List the findings to see the stage each one is in."


@dataclass
class AlreadyInStageError(NotAFindingError):
    """
    Raised when a finding is to be moved to the stage it is in already.
    """

    stage: FindingStage
    """
    The stage it is in.
    """

    def error_message(self) -> str:
        return f"#{self.number} is {self.stage.short_name} already"

    def suggest_correction(self) -> str:
        return "Nothing needs doing."


@dataclass
class PersonOnlyCommandError(DataclassException, PermissionError):
    """
    Raised when a command only the person runs is run from a Claude Code session.
    """

    command: str
    """
    The command.
    """

    def error_message(self) -> str:
        return f"{self.command} is the person's to run, never a Claude Code session's"

    def suggest_correction(self) -> str:
        return "Give the person the command line to run themselves."


@dataclass
class ForeignRepositoryError(DataclassException, PermissionError):
    """
    Raised when a repository to propose from belongs to somebody else.
    """

    repository: Repository
    """
    The repository named.
    """

    owner: str
    """
    The account whose forks are proposed from.
    """

    def error_message(self) -> str:
        return f"{self.repository} belongs to {self.repository.owner}, not {self.owner}"

    def suggest_correction(self) -> str:
        return f"Name {self.owner}'s fork, as {self.owner}/{self.repository.name}."


@dataclass
class ForkBranchDivergedError(DataclassException, ValueError):
    """
    Raised when a fork's branch to bring up to its upstream's has commits of its own.
    """

    branch: BranchName
    """
    The fork's branch.
    """

    upstream: Repository
    """
    The repository the fork was forked from.
    """

    own_commits: int
    """
    How many commits the fork's branch has that the upstream's lacks.
    """

    def error_message(self) -> str:
        return (
            f"{self.branch} has {self.own_commits} commit(s) {self.upstream}'s lacks, "
            f"so it cannot be fast-forwarded, and it is never merged or forced"
        )

    def suggest_correction(self) -> str:
        return "Ask the person what to do with those commits."


@dataclass
class UpstreamRemoteNameTakenError(DataclassException, ValueError):
    """
    Raised when the checkout configures no remote fetching from the repository a fork
    was forked from, and the remote named for that repository fetches from another.
    """

    remote: Remote
    """
    The remote holding the name.
    """

    upstream: Repository
    """
    The repository the fork was forked from.
    """

    fetched: Repository | None
    """
    The repository the remote fetches from, ``None`` when its URL names none.
    """

    def error_message(self) -> str:
        reached = self.fetched or "no repository"
        return (
            f"the checkout's remote {self.remote.name} fetches from {reached}, not "
            f"{self.upstream}, which the fork was forked from"
        )

    def suggest_correction(self) -> str:
        return (
            f"Ask the person to point the remote {self.remote.name} at "
            f"{self.upstream.rooted_clone_url()}, or to add a remote reaching it."
        )


@dataclass
class NotAForkError(DataclassException, LookupError):
    """
    Raised when a repository to propose from was forked from none.
    """

    repository: Repository
    """
    The repository named.
    """

    def error_message(self) -> str:
        return f"{self.repository} is not a fork, so it has no upstream to propose to"

    def suggest_correction(self) -> str:
        return "Open the pull request on it directly; it is the upstream itself."


@dataclass
class PullRequestNotProposableError(DataclassException, ValueError):
    """
    Raised when a fork's branch has no pull request that can be opened upstream.
    """

    branch: BranchName
    """
    The fork's branch.
    """

    reason: str
    """
    Why its pull request cannot be opened upstream.
    """

    def error_message(self) -> str:
        return f"{self.branch} cannot be opened upstream: {self.reason}"

    def suggest_correction(self) -> str:
        return "Fix what the reason names, then run the command again."


@dataclass
class NothingToEditError(DataclassException, ValueError):
    """
    Raised when a finding is to be edited with neither a new title nor a new text.
    """

    number: int
    """
    The finding.
    """

    def error_message(self) -> str:
        return f"editing finding #{self.number} was given nothing to change"

    def suggest_correction(self) -> str:
        return "Give a new title, a new text, or both."


@dataclass
class FindingNotAcceptedError(DataclassException, PermissionError):
    """
    Raised when work on a finding is asked for before the person accepted it.
    """

    number: int
    """
    The issue asked for.
    """

    def error_message(self) -> str:
        return f"#{self.number} is not an open, accepted finding"

    def suggest_correction(self) -> str:
        return "Only the person running the tool accepts a finding; ask them."


@dataclass
class AlreadyProvenError(DataclassException, ValueError):
    """
    Raised when a proven finding is to be marked unproven.
    """

    number: int
    """
    The finding.
    """

    def error_message(self) -> str:
        return f"#{self.number} is already proven"

    def suggest_correction(self) -> str:
        return (
            "If its test no longer fails, ask the person running the tool whether the "
            "finding is fixed."
        )


# %% proofs


@dataclass
class ProofPathOutsideCopyError(DataclassException, ValueError):
    """
    Raised when a posted proof places its test outside the copy of the repository it
    runs in.
    """

    path: str
    """
    The test's path, as the proof records it.
    """

    def error_message(self) -> str:
        return f"the proof's test {self.path} lies outside the repository"

    def suggest_correction(self) -> str:
        return "Prove the finding again with a test inside the repository."


@dataclass
class FileOutsideCheckoutError(DataclassException, ValueError):
    """
    Raised when a finding's test is not inside the checkout it would be committed to.
    """

    file: str
    """
    The test file.
    """

    checkout: str
    """
    The checkout's root.
    """

    def error_message(self) -> str:
        return f"{self.file} is not inside the checkout {self.checkout}"

    def suggest_correction(self) -> str:
        return "Write the test inside the checkout, where it would be committed."


@dataclass
class PassingTestError(DataclassException, ValueError):
    """
    Raised when a finding's test passes on the default branch, so it proves nothing.
    """

    test: str
    """
    The test file, relative to the repository's root.
    """

    tip: BranchTip
    """
    The default branch's commit it passed on.
    """

    def error_message(self) -> str:
        return f"{self.test} passes on {self.tip}: it shows no finding there"

    def suggest_correction(self) -> str:
        return (
            "A bug only on a work branch is no finding. Otherwise write a test that "
            "fails on the default branch, or, when none can be written, mark the "
            "finding unproven with the reason."
        )


@dataclass
class BrokenTestError(DataclassException, ValueError):
    """
    Raised when a finding's test cannot run, or fails only because the test itself is
    broken.
    """

    test: str
    """
    The test file, relative to the repository's root.
    """

    detail: str
    """
    What pytest said went wrong.
    """

    def error_message(self) -> str:
        return f"{self.test} is broken rather than failing: {self.detail}"

    def suggest_correction(self) -> str:
        return (
            "Fix the test, and run it with the interpreter the project's tests run "
            f"with ({CommandOption.PYTHON})."
        )


@dataclass
class UnprovenFindingCloseError(DataclassException, ValueError):
    """
    Raised when a session is to close a finding no proof test shows fixed.
    """

    number: int
    """
    The finding.
    """

    def error_message(self) -> str:
        return f"#{self.number} carries no proof test to show its fix landed"

    def suggest_correction(self) -> str:
        return "Leave closing it to the person running the tool, and tell them it is fixed."


@dataclass
class FixNotMergedError(DataclassException, ValueError):
    """
    Raised when a finding is to be closed as fixed by a pull request not merged into the
    default branch.
    """

    pull_request: int
    """
    The pull request named as the fix.
    """

    default_branch: BranchName
    """
    The branch it has to be merged into.
    """

    def error_message(self) -> str:
        return f"#{self.pull_request} is not merged into {self.default_branch}"

    def suggest_correction(self) -> str:
        return "Close the finding once its fix is merged, naming that pull request."


@dataclass
class FindingStillFailsError(DataclassException, ValueError):
    """
    Raised when a finding is to be closed as fixed while its proof test still fails on
    the default branch.
    """

    number: int
    """
    The finding.
    """

    tip: BranchTip
    """
    The default branch's commit the test failed on.
    """

    detail: str
    """
    Pytest's message on the failure.
    """

    def error_message(self) -> str:
        return (
            f"the test proving #{self.number} still fails on {self.tip}: {self.detail}"
        )

    def suggest_correction(self) -> str:
        return "Leave it open: its fix is not on the default branch."


@dataclass
class MissingProofError(DataclassException, LookupError):
    """
    Raised when a finding carries no proof to run again: it is not labelled proven, or
    no trusted account posted a proof on it.
    """

    number: int
    """
    The finding.
    """

    def error_message(self) -> str:
        return f"#{self.number} is not proven by a test posted on it"

    def suggest_correction(self) -> str:
        return "Prove it first, if the person running the tool asked for work on it."


@dataclass
class ProofNoLongerHoldsError(DataclassException, RuntimeError):
    """
    Raised when the test proving a finding no longer fails on the default branch.
    """

    number: int
    """
    The finding.
    """

    tip: BranchTip
    """
    The default branch's commit the test passed on.
    """

    def error_message(self) -> str:
        return f"the test proving #{self.number} no longer fails on {self.tip}"

    def suggest_correction(self) -> str:
        return "Stop, and ask the person running the tool whether the finding is fixed."


@dataclass
class UnknownPluginDataError(DataclassException, LookupError):
    """
    Raised when somebody else's repository is to be cloned and the plugin's data
    directory, where such clones go, is not known.
    """

    repository: Repository
    """
    The repository to clone.
    """

    def error_message(self) -> str:
        return (
            f"cannot clone {self.repository}: the plugin's data directory, where "
            f"somebody else's repositories are cloned, is not known; nothing was cloned"
        )

    def suggest_correction(self) -> str:
        return (
            "Run it in a Claude Code session the plugin started, or ask the person "
            "running the tool where to clone it."
        )


@dataclass
class DiscussionsDisabledError(DataclassException, LookupError):
    """
    Raised when something is to be posted to the Discussions of a repository that has
    them turned off.
    """

    repository: Repository
    """
    The repository.
    """

    def error_message(self) -> str:
        return f"{self.repository} has Discussions turned off; nothing was queued"

    def suggest_correction(self) -> str:
        return (
            "Ask the person running the tool to turn Discussions on in the repository's "
            "settings, or to say where else the idea should go."
        )


# %% upstream reviews


@dataclass
class ForeignReviewAddressError(DataclassException, ValueError):
    """
    Raised when an address said to be addressed is not on a pull request of the
    repository the owner's was forked from.
    """

    address: str
    """
    The address given.
    """

    upstream: Repository | None
    """
    The repository the owner's was forked from, ``None`` when it is no fork.
    """

    def error_message(self) -> str:
        if self.upstream is None:
            return f"{self.address} is no upstream review: the repository is no fork"
        return f"{self.address} is not on a pull request of {self.upstream}"

    def suggest_correction(self) -> str:
        return "Give the address `review list` shows for the upstream comment."


@dataclass
class UnknownUpstreamCommentError(DataclassException, LookupError):
    """
    Raised when a number said to be addressed is no comment on the pull request opened
    upstream.
    """

    number: int
    """
    The number given.
    """

    upstream_url: str
    """
    The pull request opened upstream.
    """

    def error_message(self) -> str:
        return f"{self.number} is no review comment on {self.upstream_url}"

    def suggest_correction(self) -> str:
        return (
            "Give the number `review list` shows first on the upstream comment's line, "
            "or the address at its end."
        )


# %% why the upstream reviews could not be read


@dataclass
class UpstreamReviewsUnavailable(DataclassException, ABC):
    """
    Why the pull request opened upstream could not be read; returned in place of its
    reviews rather than raised.
    """

    def line(self) -> str:
        """:return: What kept it from being read and what to do about it, in one line."""
        return (
            f"upstream reviews not read: {self.error_message()}. "
            f"{self.suggest_correction()}"
        )


@dataclass
class UpstreamReadNotStarted(UpstreamReviewsUnavailable):
    """
    The fork's Actions started no run answering the request: Actions are off on the
    fork, or its workflows are, or GitHub dropped the push.
    """

    fork: Repository
    """
    The fork.
    """

    start_seconds: float
    """
    How long each request's run was waited for.
    """

    def error_message(self) -> str:
        return (
            f"{self.fork}'s Actions started no run reading them within "
            f"{self.start_seconds:.0f} seconds of each request"
        )

    def suggest_correction(self) -> str:
        return (
            f"Ask the person to check that Actions and the fork's workflows are on at "
            f"{self.fork.url}/actions, then list the reviews again"
        )


@dataclass
class UpstreamAnswerUnreadable(UpstreamReviewsUnavailable):
    """
    The fork's Actions answered the request, but this session's code cannot read the
    answer back.
    """

    problem: str
    """
    What is wrong with the answer.
    """

    recorder: CodeVersion | None
    """
    The code that recorded it, ``None`` when the answer does not say.
    """

    replayer: CodeVersion
    """
    The code this session runs.
    """

    def error_message(self) -> str:
        return f"the fork's Actions answered, but {self.problem}"

    def suggest_correction(self) -> str:
        if self.recorder is None:
            return (
                "Ask again: the answer was saved by an older version of the workflow."
            )
        if self.recorder != self.replayer:
            return (
                f"Update the plugin: the answer was recorded by "
                f"{self.recorder.described}, this session runs "
                f"{self.replayer.described}."
            )
        return "Ask for the upstream reviews again."


@dataclass
class UpstreamReadFailed(UpstreamReviewsUnavailable):
    """
    The fork's Actions run answering the request failed.
    """

    run: str
    """
    The run's page, with its log.
    """

    conclusion: WorkflowRunConclusion
    """
    How it ended.
    """

    def error_message(self) -> str:
        return f"the run reading them ended in {self.conclusion}: {self.run}"

    def suggest_correction(self) -> str:
        return "Read its log, and file what went wrong as a finding of the workflow"


@dataclass
class UpstreamReadUnanswered(UpstreamReviewsUnavailable):
    """
    The fork's Actions did not answer the request in time.
    """

    upstream: Repository
    """
    The repository the pull request is open on.
    """

    timeout_seconds: float
    """
    How long the answer was waited for.
    """

    def error_message(self) -> str:
        return (
            f"the fork's Actions did not read them on {self.upstream} within "
            f"{self.timeout_seconds:.0f} seconds"
        )

    def suggest_correction(self) -> str:
        return "List the reviews again; the run reading them may still be going"


# %% installing the runtime


@dataclass
class RuntimeInstallError(DataclassException, RuntimeError):
    """
    Raised when a step building the runtime fails; the build is removed, and the runtime
    in use left alone.
    """

    step: str
    """
    The step that failed.
    """

    said: str
    """
    The last line the step wrote, on its error output or else its output.
    """

    def error_message(self) -> str:
        return f"installing the runtime failed at {self.step}: {self.said}"

    def suggest_correction(self) -> str:
        return ""
