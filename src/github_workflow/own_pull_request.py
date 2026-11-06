"""
Writing to the work branch's own pull request, without asking: labelling it, and
replying to and resolving its review threads.
"""

from __future__ import annotations

from dataclasses import dataclass

from basstler_domain_model.git.commands import RemoteBranch
from basstler_domain_model.github.readers import PullRequestSource
from basstler_domain_model.github.repository_client import (
    IssueBoard,
    PullRequestsFromForks,
    RepositoryLabels,
)
from basstler_domain_model.github.rest_models import RestPullRequest
from basstler_domain_model.github.review_models import ReviewThread
from basstler_domain_model.github.review_writers import ReviewThreadWriter
from basstler_domain_model.github.vocabulary import PullRequestState

from github_workflow.exceptions import (
    NoOpenPullRequestError,
    NothingToLabelError,
    PersonOnlyLabelError,
    ReviewThreadNotFoundError,
    UnknownLabelError,
    UnpushedWorkError,
)
from github_workflow.policy import WritePolicy
from github_workflow.pull_request_overview import PullRequestLabel
from github_workflow.work import WorkflowStep

# %% the work branch's pull request


@dataclass(frozen=True)
class WorkBranchPullRequest:
    """
    The open pull request opened from the checked-out work branch, on the owner's
    repository: the only one these commands write to.
    """

    policy: WritePolicy
    """
    The checkout, its work branch and the owner's remote.
    """

    pull_requests: PullRequestsFromForks
    """
    Finds the pull requests opened from the branch.
    """

    def find(self) -> RestPullRequest:
        """
        :return: The open pull request from the work branch.
        :raises DefaultBranchWriteError: If the default branch is checked out.
        :raises NoOpenPullRequestError: If the branch has no open pull request.
        """
        branch = self.policy.work_branch()
        owner = self.policy.remote.repository.owner
        opened = [
            pull_request
            for pull_request in self.pull_requests.pull_requests_from(owner, branch)
            if pull_request.state is PullRequestState.OPEN
        ]
        if not opened:
            raise NoOpenPullRequestError(branch)
        return opened[0]


# %% labels


@dataclass(frozen=True)
class PullRequestLabelling(WorkflowStep):
    """
    Labels of the repository's own added to the work branch's pull request, and labels
    it carries removed.

    :raises NothingToLabelError: If no label is named.
    :raises PersonOnlyLabelError: If a label to add or remove is one only the person
        sets.
    :raises UnknownLabelError: If a label to add is not one of the repository's.
    """

    pull_request: WorkBranchPullRequest
    """
    The work branch's pull request.
    """

    labels: RepositoryLabels
    """
    Reads the repository's labels.
    """

    board: IssueBoard
    """
    Adds and removes the pull request's labels, a pull request being an issue to GitHub
    too.
    """

    added: tuple[str, ...]
    """
    The labels to add.
    """

    removed: tuple[str, ...]
    """
    The labels to remove.
    """

    def run(self) -> str:
        if not self.added and not self.removed:
            raise NothingToLabelError(self.pull_request.policy.work_branch())
        if PullRequestLabel.SHELVED in {*self.added, *self.removed}:
            raise PersonOnlyLabelError(PullRequestLabel.SHELVED)
        unknown = sorted(set(self.added) - self.labels.labels())
        if unknown:
            raise UnknownLabelError(tuple(unknown))
        found = self.pull_request.find()
        if self.added:
            self.board.add_labels(found.number, list(self.added))
        carried = [label for label in self.removed if label in found.labels]
        for label in carried:
            self.board.remove_label(found.number, label)
        changes = [f"added {', '.join(self.added)}"] if self.added else []
        changes += [f"removed {', '.join(carried)}"] if carried else []
        return f"labels of #{found.number}: {'; '.join(changes) or 'unchanged'}"


# %% review threads


@dataclass(frozen=True)
class ReviewThreads:
    """
    The review threads of the work branch's pull request, each named by its first
    comment's identifier, which every API GitHub offers has.
    """

    pull_request: WorkBranchPullRequest
    """
    The work branch's pull request.
    """

    source: PullRequestSource
    """
    Reads the threads, through whichever API the place it runs in reaches.
    """

    def read(self) -> tuple[RestPullRequest, list[ReviewThread]]:
        """
        :return: The pull request, and its threads, unresolved first.
        """
        found = self.pull_request.find()
        read = self.source.read_current_state(found.number).threads
        return found, sorted(read, key=lambda thread: thread.is_resolved)

    def thread(self, comment: int) -> tuple[RestPullRequest, ReviewThread]:
        """
        :param comment: The identifier of a comment in the thread.
        :return: The pull request, and the thread.
        :raises ReviewThreadNotFoundError: If the pull request has no such thread.
        """
        found, read = self.read()
        for thread in read:
            if comment in [each.database_identifier for each in thread.comments]:
                return found, thread
        raise ReviewThreadNotFoundError(found.number, comment)


@dataclass(frozen=True)
class ReviewThreadListing(WorkflowStep):
    """
    The review threads of the work branch's pull request, unresolved first, one per
    line, each starting with the identifier the other review commands take.
    """

    pull_request: WorkBranchPullRequest
    """
    The work branch's pull request.
    """

    source: PullRequestSource
    """
    Reads the threads.
    """

    def run(self) -> str:
        """
        :return: One thread per line; overrides :meth:`WorkflowStep.run`, which
            reports in one line.
        """
        found, read = ReviewThreads(self.pull_request, self.source).read()
        lines = []
        for thread in read:
            first = thread.comments[0]
            state = "resolved" if thread.is_resolved else "unresolved"
            state += ", outdated" if thread.is_outdated else ""
            said = first.body.splitlines()[0] if first.body else ""
            lines.append(
                f"{first.database_identifier} ({state}) {thread.location}: "
                f"{first.author.login}: {said}"
            )
        return "\n".join(lines) or f"#{found.number} has no review threads"


@dataclass(frozen=True)
class ReviewReply(WorkflowStep):
    """
    A reply in a review thread of the work branch's pull request.

    :raises ReviewThreadNotFoundError: If the pull request has no such thread.
    """

    pull_request: WorkBranchPullRequest
    """
    The work branch's pull request.
    """

    source: PullRequestSource
    """
    Reads the threads.
    """

    writer: ReviewThreadWriter
    """
    Writes the reply.
    """

    comment: int
    """
    The identifier of a comment in the thread.
    """

    body: str
    """
    The reply.
    """

    def run(self) -> str:
        found, thread = ReviewThreads(self.pull_request, self.source).thread(
            self.comment
        )
        url = self.writer.reply(found.number, thread, self.body)
        return f"replied in the thread at {thread.location} on #{found.number}: {url}"


@dataclass(frozen=True)
class ReviewResolution(WorkflowStep):
    """
    A review thread of the work branch's pull request resolved, once every commit of the
    branch is pushed, so the fix it answers is on GitHub.

    :raises UnpushedWorkError: If the branch has commits GitHub's copy lacks.
    :raises ReviewThreadNotFoundError: If the pull request has no such thread.
    """

    pull_request: WorkBranchPullRequest
    """
    The work branch's pull request.
    """

    source: PullRequestSource
    """
    Reads the threads.
    """

    writer: ReviewThreadWriter
    """
    Resolves the thread.
    """

    comment: int
    """
    The identifier of a comment in the thread.
    """

    def run(self) -> str:
        policy = self.pull_request.policy
        branch = RemoteBranch(policy.remote.name, policy.work_branch())
        git = policy.checkout.git
        fetched = git.fetch_branch(branch)
        pushed = fetched.succeeded and git.contains("HEAD", branch.tracking_reference)
        if not pushed:
            raise UnpushedWorkError(branch.name)
        found, thread = ReviewThreads(self.pull_request, self.source).thread(
            self.comment
        )
        if thread.is_resolved:
            return f"the thread at {thread.location} on #{found.number} is resolved"
        self.writer.resolve(found.number, thread)
        return f"resolved the thread at {thread.location} on #{found.number}"
