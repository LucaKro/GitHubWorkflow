"""
The errors the workflow's commands end in.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from basstler_domain_model.exceptions import DataclassException

if TYPE_CHECKING:
    from basstler_domain_model.repository import Repository

    from github_workflow.proofs import BranchTip

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


# %% saving notes


@dataclass
class NotesBlockMissingError(DataclassException, LookupError):
    """
    Raised when saving finds no notes block in ``CLAUDE.local.md``.
    """

    document: str
    """
    The file that was read.
    """

    def error_message(self) -> str:
        return f"{self.document} holds no github-workflow notes block"

    def suggest_correction(self) -> str:
        return "Start a session first, which writes the block, then edit inside it."


# %% stacking


@dataclass
class StackContinuesAboveError(DataclassException, ValueError):
    """
    Raised when a pull request is to go on top of one that other pull requests in its
    stack already build on.
    """

    below: int
    """
    The pull request that was to be built on.
    """

    above: tuple[int, ...]
    """
    The pull requests the stack already holds above it.
    """

    def error_message(self) -> str:
        holders = ", ".join(f"#{number}" for number in self.above)
        return f"#{self.below} already has {holders} stacked on it; a stack is a single line"

    def suggest_correction(self) -> str:
        return "Stack the pull request on the top of that stack instead."


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

    branch: str
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

    branch: str
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

    branch: str
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

    branch: str
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

    branch: str
    """
    The work branch.
    """

    merged_branch: str
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
        return (
            "Edit those files to their resolved content, keeping both sides' intent and "
            f"no conflict markers, then run `sync --continue {' '.join(self.files)}`. "
            "To give up instead, run `sync --abort`, which leaves the branch as it was."
        )


@dataclass
class MergeInProgressError(DataclassException, RuntimeError):
    """
    Raised when the work branch is committed to, pushed or merged into while a merge is
    in progress on it.
    """

    branch: str
    """
    The work branch.
    """

    def error_message(self) -> str:
        return f"a merge is in progress on {self.branch}"

    def suggest_correction(self) -> str:
        return (
            "Finish it with `sync --continue <resolved files>`, or undo it with "
            "`sync --abort`."
        )


@dataclass
class NoMergeInProgressError(DataclassException, RuntimeError):
    """
    Raised when a merge is to be finished or undone and none is in progress.
    """

    branch: str
    """
    The work branch.
    """

    def error_message(self) -> str:
        return f"no merge is in progress on {self.branch}"

    def suggest_correction(self) -> str:
        return "Start one with `sync --base` or `sync --on <number>`."


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
class StackedBranchMergeError(DataclassException, ValueError):
    """
    Raised when the default branch is to be merged into a branch whose pull request sits
    higher in a stack, targeting the branch below it.
    """

    branch: str
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
        return (
            "Merge the default branch into the stack's bottom pull request, and its "
            "branch into this one with `sync --on <number>`; or use GitHub's Rebase "
            "stack."
        )


@dataclass
class BranchDeletedFromGitHubError(DataclassException, LookupError):
    """
    Raised when a branch that was on GitHub is no longer there, as after its pull
    request was merged.
    """

    branch: str
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
class NoOpenPullRequestError(DataclassException, LookupError):
    """
    Raised when the work branch has no open pull request to write to.
    """

    branch: str
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

    branch: str
    """
    The work branch.
    """

    def error_message(self) -> str:
        return f"labelling {self.branch}'s pull request was given no label"

    def suggest_correction(self) -> str:
        return "Name a label to add with --add, or to remove with --remove."


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

    branch: str
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

    branch: str
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

    branch: str
    """
    The branch.
    """

    def error_message(self) -> str:
        return f"{self.branch} is not on GitHub, so there is nothing to delete"

    def suggest_correction(self) -> str:
        return "Only a branch on GitHub is discarded; leave this one as it is."


# %% findings


@dataclass
class NotAFindingError(DataclassException, LookupError):
    """
    Raised when a finding to be accepted, shelved, rejected, proven or marked unproven
    is none, or not in a stage that allows it.
    """

    number: int
    """
    The issue asked for.
    """

    def error_message(self) -> str:
        return f"#{self.number} is not an open finding that can be changed this way"

    def suggest_correction(self) -> str:
        return "List the findings to see the stage each one is in."


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

    branch: str
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

    branch: str
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
            "with (--python)."
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

    default_branch: str
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
