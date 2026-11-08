"""
Writing to the work branch's own pull request, without asking: labelling it, and
replying to and resolving its review threads.
"""

from __future__ import annotations

import time
from abc import ABC
from dataclasses import dataclass

from basstler_domain_model.git.commands import RemoteBranch
from basstler_domain_model.github.readers import PullRequestSource
from basstler_domain_model.github.repository_client import (
    Commenter,
    ForkDetails,
    IssueBoard,
    PullRequestsFromForks,
    RepositoryLabels,
)
from basstler_domain_model.github.rest_models import RestPullRequest
from basstler_domain_model.github.review_models import ReviewThread
from basstler_domain_model.github.review_writers import ReviewThreadWriter
from basstler_domain_model.github.vocabulary import PullRequestState

from github_workflow.exceptions import (
    ForeignReviewAddressError,
    NoOpenPullRequestError,
    NothingToLabelError,
    PersonOnlyLabelError,
    ReviewThreadNotFoundError,
    UnknownLabelError,
    UnpushedWorkError,
    UpstreamReviewsUnavailable,
)
from github_workflow.labels import PullRequestLabel, UpstreamLabel
from github_workflow.policy import WritePolicy
from github_workflow.upstream_reviews import UpstreamReviewRequest, UpstreamReviews
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
    line, each starting with the identifier the other review commands take; and, when
    the pull request was opened upstream, the reviews and threads of the one upstream,
    each comment with its address.
    """

    pull_request: WorkBranchPullRequest
    """
    The work branch's pull request.
    """

    source: PullRequestSource
    """
    Reads the threads.
    """

    fork: ForkDetails
    """
    Reads which repository the owner's was forked from.
    """

    upstream_reviews: UpstreamReviews
    """
    Reads the pull request opened upstream.
    """

    def run(self) -> str:
        """
        :return: One thread per line; overrides :meth:`WorkflowStep.run`, which
            reports in one line.
        """
        found, read = ReviewThreads(self.pull_request, self.source).read()
        lines = [self.described(thread) for thread in read]
        lines = lines or [f"#{found.number} has no review threads"]
        if UpstreamLabel.OPENED_UPSTREAM not in found.labels:
            return "\n".join(lines)
        upstream = self.fork.upstream()
        if upstream is None:
            return "\n".join(lines)
        policy = self.pull_request.policy
        snapshot = self.upstream_reviews.snapshot(
            UpstreamReviewRequest(
                upstream,
                policy.remote.repository.owner,
                policy.work_branch(),
                f"{time.time_ns()}.json",
            )
        )
        if isinstance(snapshot, UpstreamReviewsUnavailable):
            lines.append(snapshot.line())
            return "\n".join(lines)
        lines.append(f"upstream {upstream}#{snapshot.number} {snapshot.url}:")
        lines += [
            f"review by {review.author.login} ({review.state}): "
            f"{''.join(review.body.splitlines()[:1])}"
            for review in snapshot.reviews
        ]
        lines += [
            f"{self.described(thread)} {thread.comments[0].url}"
            for thread in sorted(snapshot.threads, key=lambda each: each.is_resolved)
        ]
        return "\n".join(lines)

    @staticmethod
    def described(thread: ReviewThread) -> str:
        """
        :param thread: A review thread.
        :return: It in one line: its first comment's identifier, whether it is
            resolved, where it is, and who said what first.
        """
        first = thread.comments[0]
        state = "resolved" if thread.is_resolved else "unresolved"
        state += ", outdated" if thread.is_outdated else ""
        said = first.body.splitlines()[0] if first.body else ""
        return (
            f"{first.database_identifier} ({state}) {thread.location}: "
            f"{first.author.login}: {said}"
        )


@dataclass(frozen=True)
class ReviewThreadWrite(WorkflowStep, ABC):
    """
    A write to one review thread of the work branch's pull request.

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
    Writes to the thread.
    """

    comment: int
    """
    The identifier of a comment in the thread.
    """

    def thread(self) -> tuple[RestPullRequest, ReviewThread]:
        """
        :return: The work branch's pull request, and the thread holding the comment.
        :raises ReviewThreadNotFoundError: If the pull request has no such thread.
        """
        return ReviewThreads(self.pull_request, self.source).thread(self.comment)


@dataclass(frozen=True)
class ReviewReply(ReviewThreadWrite):
    """
    A reply in a review thread of the work branch's pull request.
    """

    body: str
    """
    The reply.
    """

    def run(self) -> str:
        found, thread = self.thread()
        url = self.writer.reply(found.number, thread, self.body)
        return f"replied in the thread at {thread.location} on #{found.number}: {url}"


@dataclass(frozen=True)
class ReviewResolution(ReviewThreadWrite):
    """
    A review thread of the work branch's pull request resolved, once every commit of the
    branch is pushed, so the fix it answers is on GitHub.

    :raises UnpushedWorkError: If the branch has commits GitHub's copy lacks.
    """

    def run(self) -> str:
        policy = self.pull_request.policy
        branch = RemoteBranch(policy.remote.name, policy.work_branch())
        git = policy.checkout.git
        fetched = git.fetch_branch(branch)
        pushed = fetched.succeeded and git.contains("HEAD", branch.tracking_reference)
        if not pushed:
            raise UnpushedWorkError(branch.name)
        found, thread = self.thread()
        if thread.is_resolved:
            return f"the thread at {thread.location} on #{found.number} is resolved"
        self.writer.resolve(found.number, thread)
        return f"resolved the thread at {thread.location} on #{found.number}"


@dataclass(frozen=True)
class ReviewAddressing(WorkflowStep):
    """
    A comment on the work branch's pull request saying what was changed for a review
    comment on the pull request opened upstream, linking it; nothing is written
    upstream.

    :raises ForeignReviewAddressError: If the address is not on a pull request of the
        repository the owner's was forked from.
    """

    pull_request: WorkBranchPullRequest
    """
    The work branch's pull request.
    """

    fork: ForkDetails
    """
    Reads which repository the owner's was forked from.
    """

    commenter: Commenter
    """
    Writes the comment.
    """

    address: str
    """
    The address of the review comment upstream.
    """

    body: str
    """
    What was changed for it.
    """

    def run(self) -> str:
        upstream = self.fork.upstream()
        if upstream is None or not self.address.startswith(f"{upstream.url}/pull/"):
            raise ForeignReviewAddressError(self.address, upstream)
        found = self.pull_request.find()
        url = self.commenter.add_comment(
            found.number, f"Addressed upstream: {self.address}\n\n{self.body}"
        )
        return f"commented on #{found.number}: {url}"
