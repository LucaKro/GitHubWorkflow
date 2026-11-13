"""
Writing to the work branch's own pull request, without asking: labelling it, and
replying to and resolving its review threads.
"""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass

from domain_model.github.readers import PullRequestSource
from domain_model.github.repository_client import (
    ForkCommenter,
    ForkDetails,
    IssueTracker,
    PullRequestsFromForks,
)
from domain_model.github.rest_models import RestPullRequest
from domain_model.github.review_models import ReviewThread
from domain_model.github.review_writers import ReviewThreadWriter
from domain_model.repository import Repository

from github_workflow.exceptions import (
    ForeignReviewAddressError,
    ForwardedReadUnavailable,
    NoOpenPullRequestError,
    NothingToLabelError,
    PersonOnlyLabelError,
    ReviewThreadNotFoundError,
    UnknownLabelError,
    UnknownUpstreamCommentError,
    UnpushedWorkError,
)
from github_workflow.labels import PullRequestLabel, UpstreamLabel
from github_workflow.policy import WritePolicy
from github_workflow.upstream_reviews import UpstreamReviews
from github_workflow.workflow_step import WorkflowStep

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
        opened = self.pull_requests.open_fork_branch_pull_requests(owner, branch)
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

    issues: IssueTracker
    """
    The repository's labels, and its issues, a pull request being an issue to GitHub
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
        unknown = sorted(set(self.added) - self.issues.labels())
        if unknown:
            raise UnknownLabelError(tuple(unknown))
        found = self.pull_request.find()
        if self.added:
            self.issues.add_labels(found.number, list(self.added))
        carried = [label for label in self.removed if label in found.labels]
        for label in carried:
            self.issues.remove_label(found.number, label)
        changes = [f"added {', '.join(self.added)}"] if self.added else []
        changes += [f"removed {', '.join(carried)}"] if carried else []
        return f"labels of #{found.number}: {'; '.join(changes) or 'unchanged'}"


# %% review threads


@dataclass(frozen=True)
class ThreadedPullRequest:
    """
    A pull request, and its review threads, unresolved first.
    """

    pull_request: RestPullRequest
    """
    The pull request.
    """

    threads: list[ReviewThread]
    """
    Its review threads, unresolved first.
    """


@dataclass(frozen=True)
class PullRequestThread:
    """
    One review thread, and the pull request it is on.
    """

    pull_request: RestPullRequest
    """
    The pull request.
    """

    thread: ReviewThread
    """
    The thread.
    """


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

    def read(self) -> ThreadedPullRequest:
        """
        :return: The pull request, and its threads.
        """
        found = self.pull_request.find()
        read = self.source.read_current_state(found.number).threads
        return ThreadedPullRequest(
            found, sorted(read, key=lambda thread: thread.is_resolved)
        )

    def thread(self, comment: int) -> PullRequestThread:
        """
        :param comment: The identifier of a comment in the thread.
        :return: The thread holding the comment.
        :raises ReviewThreadNotFoundError: If the pull request has no such thread.
        """
        threaded = self.read()
        for thread in threaded.threads:
            if comment in [each.database_identifier for each in thread.comments]:
                return PullRequestThread(threaded.pull_request, thread)
        raise ReviewThreadNotFoundError(threaded.pull_request.number, comment)


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
        threaded = ReviewThreads(self.pull_request, self.source).read()
        found = threaded.pull_request
        lines = [self.describe_thread(thread) for thread in threaded.threads]
        lines = lines or [f"#{found.number} has no review threads"]
        if UpstreamLabel.OPENED_UPSTREAM not in found.labels:
            return "\n".join(lines)
        upstream = self.fork.upstream()
        if upstream is None:
            return "\n".join(lines)
        snapshot = self.upstream_reviews.read_work_branch_snapshot(
            upstream, self.pull_request.policy
        )
        if isinstance(snapshot, ForwardedReadUnavailable):
            lines.append(snapshot.line())
            return "\n".join(lines)
        lines.append(f"upstream {upstream}#{snapshot.number} {snapshot.url}:")
        lines += [
            f"review by {review.author.login} ({review.state}): "
            f"{''.join(review.body.splitlines()[:1])}"
            for review in snapshot.reviews
        ]
        lines += [
            " ".join(
                [self.describe_thread(thread)]
                + [comment.url for comment in thread.comments[:1]]
            )
            for thread in sorted(snapshot.threads, key=lambda each: each.is_resolved)
        ]
        return "\n".join(lines)

    @staticmethod
    def describe_thread(thread: ReviewThread) -> str:
        """
        :param thread: A review thread.
        :return: It in one line: its first comment's identifier, whether it is
            resolved, where it is, and who said what first; for a thread whose
            comments are not visible, such as one of a pending review, that it has
            none to show.
        """
        state = "resolved" if thread.is_resolved else "unresolved"
        state += ", outdated" if thread.is_outdated else ""
        if not thread.comments:
            return (
                f"- ({state}) {thread.location}: no visible comments, such as those "
                f"of a review still pending"
            )
        first = thread.comments[0]
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

    def thread(self) -> PullRequestThread:
        """
        :return: The thread holding the comment, on the work branch's pull request.
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
        found = self.thread()
        number = found.pull_request.number
        url = self.writer.reply(number, found.thread, self.body)
        return f"replied in the thread at {found.thread.location} on #{number}: {url}"


@dataclass(frozen=True)
class ReviewResolution(ReviewThreadWrite):
    """
    A review thread of the work branch's pull request resolved, once every commit of the
    branch is pushed, so the fix it answers is on GitHub.

    :raises UnpushedWorkError: If the branch has commits GitHub's copy lacks.
    """

    def run(self) -> str:
        policy = self.pull_request.policy
        branch = policy.remote.branch(policy.work_branch())
        fetched = branch.fetch()
        head = policy.checkout.working_tree.head()
        pushed = fetched.succeeded and head.is_contained_in(branch.tracking_branch)
        if not pushed:
            raise UnpushedWorkError(branch.name)
        found = self.thread()
        number, thread = found.pull_request.number, found.thread
        if thread.is_resolved:
            return f"the thread at {thread.location} on #{number} is resolved"
        self.writer.resolve(number, thread)
        return f"resolved the thread at {thread.location} on #{number}"


@dataclass(frozen=True)
class ReviewAddressing(WorkflowStep):
    """
    A comment on the work branch's pull request saying what was changed for a review
    comment on the pull request opened upstream, linking it; nothing is written
    upstream.

    :raises ForeignReviewAddressError: If the address is not on a pull request of the
        repository the owner's was forked from.
    :raises UnknownUpstreamCommentError: If a comment's number is given, and the pull
        request opened upstream has no review comment of that number.
    :raises ForwardedReadUnavailable: If a comment's number is given, and the pull
        request opened upstream could not be read.
    """

    pull_request: WorkBranchPullRequest
    """
    The work branch's pull request.
    """

    fork: ForkCommenter
    """
    Reads which repository the owner's was forked from, and writes the comment.
    """

    address: str
    """
    The address of the review comment upstream, or its number as
    :class:`ReviewThreadListing` shows it.
    """

    body: str
    """
    What was changed for it.
    """

    upstream_reviews: UpstreamReviews
    """
    Reads the pull request opened upstream, to find a comment given by its number.
    """

    def run(self) -> str:
        upstream = self.fork.upstream()
        if upstream is None:
            raise ForeignReviewAddressError(self.address, upstream)
        address = self.address
        if address.isdigit():
            address = self.comment_address(upstream, int(address))
        if not upstream.is_pull_request_page(address):
            raise ForeignReviewAddressError(address, upstream)
        found = self.pull_request.find()
        url = self.fork.add_comment(
            found.number, f"Addressed upstream: {address}\n\n{self.body}"
        )
        return f"commented on #{found.number}: {url}"

    def comment_address(self, upstream: Repository, number: int) -> str:
        """
        :param upstream: The repository the owner's was forked from.
        :param number: A review comment's number on the pull request opened upstream.
        :return: The comment's address.
        :raises UnknownUpstreamCommentError: If no review comment has that number.
        :raises ForwardedReadUnavailable: If the pull request could not be read.
        """
        snapshot = self.upstream_reviews.read_work_branch_snapshot(
            upstream, self.pull_request.policy
        )
        if isinstance(snapshot, ForwardedReadUnavailable):
            raise snapshot
        addresses = [
            comment.url
            for thread in snapshot.threads
            for comment in thread.comments
            if comment.database_identifier == number
        ]
        if not addresses:
            raise UnknownUpstreamCommentError(number, snapshot.url)
        return addresses[0]
