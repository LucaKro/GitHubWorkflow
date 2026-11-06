"""
Tests for :mod:`github_workflow.own_pull_request`: the work branch's own pull request
labelled, and its review threads listed, replied to and resolved, without asking.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import pytest

from basstler_domain_model.github.pull_request_models import UpstreamPullRequestSnapshot
from basstler_domain_model.github.review_models import (
    Author,
    BranchPullRequest,
    ReviewThread,
    ThreadComment,
)
from basstler_domain_model.github.repository_client import Commenter, ForkDetails
from basstler_domain_model.github.rest_models import RestPullRequest
from basstler_domain_model.github.review_models import Review
from basstler_domain_model.github.review_writers import ReviewThreadWriter
from basstler_domain_model.github.readers import PullRequestSource
from basstler_domain_model.github.vocabulary import PullRequestState, ReviewState
from basstler_domain_model.repository import Repository

from github_workflow.exceptions import (
    ForeignReviewAddressError,
    NoOpenPullRequestError,
    NothingToLabelError,
    PersonOnlyLabelError,
    ReviewThreadNotFoundError,
    UnknownLabelError,
    UnpushedWorkError,
)
from github_workflow.own_pull_request import (
    PullRequestLabelling,
    ReviewAddressing,
    ReviewReply,
    ReviewResolution,
    ReviewThreadListing,
    WorkBranchPullRequest,
)
from github_workflow.policy import WritePolicy
from github_workflow.pull_request_overview import PullRequestLabel
from github_workflow.upstream import UpstreamLabel
from github_workflow.upstream_reviews import UpstreamReviewRequest, UpstreamReviews

from .issues_in_memory import IssuesInMemory
from .pull_requests import REPOSITORY, pull_request
from .test_work import PullRequestsFromBranchesInMemory, work  # noqa: F401

# %% the work branch's pull request


def own(work: WritePolicy, *opened) -> WorkBranchPullRequest:  # noqa: F811
    """
    :param work: The rules of a clone on the pushed work branch ``feature``.
    :param opened: The pull requests opened from its branches.
    :return: The work branch's own pull request, among them.
    """
    return WorkBranchPullRequest(work, PullRequestsFromBranchesInMemory(list(opened)))


def test_a_branch_without_an_open_pull_request_has_none_to_write_to(
    work: WritePolicy,  # noqa: F811
):
    closed = pull_request(3, "feature", state=PullRequestState.CLOSED)

    with pytest.raises(NoOpenPullRequestError):
        own(work, closed).find()


# %% labels


def labelled() -> IssuesInMemory:
    """
    :return: A board whose repository has the labels ``bug-fix`` and ``api-break``.
    """
    return IssuesInMemory({}, {"bug-fix", "api-break"})


def test_labels_the_repository_has_are_added_to_the_pull_request(
    work: WritePolicy,  # noqa: F811
):
    board = labelled()

    PullRequestLabelling(
        own(work, pull_request(3, "feature")), board, board, ("bug-fix",), ()
    ).run()

    assert board.writes == [f"add_labels 3 {['bug-fix']}"]


def test_a_label_the_repository_lacks_is_refused_before_anything_is_written(
    work: WritePolicy,  # noqa: F811
):
    board = labelled()

    with pytest.raises(UnknownLabelError):
        PullRequestLabelling(
            own(work, pull_request(3, "feature")), board, board, ("made-up",), ()
        ).run()

    assert board.writes == []


def test_only_labels_the_pull_request_carries_are_removed(
    work: WritePolicy,  # noqa: F811
):
    board = labelled()
    carrying = replace(pull_request(3, "feature"), labels=("api-break",))

    PullRequestLabelling(
        own(work, carrying), board, board, (), ("api-break", "bug-fix")
    ).run()

    assert board.writes == ["remove_label 3 api-break"]


def test_labelling_nothing_is_refused(work: WritePolicy):  # noqa: F811
    board = labelled()

    with pytest.raises(NothingToLabelError):
        PullRequestLabelling(
            own(work, pull_request(3, "feature")), board, board, (), ()
        ).run()


@pytest.mark.parametrize(
    "added, removed",
    [((PullRequestLabel.SHELVED,), ()), ((), (PullRequestLabel.SHELVED,))],
    ids=["shelving", "unshelving"],
)
def test_shelving_is_left_to_the_person(
    work: WritePolicy, added: tuple[str, ...], removed: tuple[str, ...]  # noqa: F811
):
    board = IssuesInMemory({}, {PullRequestLabel.SHELVED})
    carrying = replace(pull_request(3, "feature"), labels=removed)

    with pytest.raises(PersonOnlyLabelError):
        PullRequestLabelling(own(work, carrying), board, board, added, removed).run()

    assert board.writes == []


# %% review threads


def thread(first: int, resolved: bool = False) -> ReviewThread:
    """
    :param first: The identifier of its first comment.
    :param resolved: Whether it is resolved.
    :return: A thread on ``src/module.py``.
    """
    comment = ThreadComment(
        database_identifier=first,
        author=Author("a-reviewer"),
        body=f"Comment {first}.\nMore.",
        created_at="2026-11-04T10:00:00Z",
        url=f"https://github.com/{REPOSITORY}/pull/3#discussion_r{first}",
    )
    return ReviewThread(
        identifier=f"thread-{first}",
        is_resolved=resolved,
        is_outdated=False,
        path="src/module.py",
        line=first,
        comments=[comment],
    )


@dataclass(frozen=True)
class ThreadsInMemory(PullRequestSource):
    """
    Answers every pull request with the threads given.
    """

    threads: list[ReviewThread] = field(default_factory=list)
    """
    The threads.
    """

    def resolve_pull_request_number(self, branch: str) -> int:
        raise NotImplementedError

    def read_current_state(
        self, pull_request_number: int
    ) -> UpstreamPullRequestSnapshot:
        return UpstreamPullRequestSnapshot(
            pull_request_number, "A title", "https://pull", [], self.threads, None
        )

    def choose(self, branch: str, pull_requests: list[BranchPullRequest]) -> int:
        raise NotImplementedError


@dataclass(frozen=True)
class ThreadWriterInMemory(ReviewThreadWriter):
    """
    Records every reply and resolution.
    """

    written: list[str] = field(default_factory=list)
    """
    Every write, in order.
    """

    def reply(self, number: int, thread: ReviewThread, body: str) -> str:
        self.written.append(f"reply {number} {thread.identifier} {body}")
        return "https://reply"

    def resolve(self, number: int, thread: ReviewThread) -> None:
        self.written.append(f"resolve {number} {thread.identifier}")


def threads(*listed: ReviewThread) -> ThreadsInMemory:
    """:param listed: The threads.
    :return: A source answering with them."""
    return ThreadsInMemory(list(listed))


def writer() -> ThreadWriterInMemory:
    """:return: A writer recording what it writes."""
    return ThreadWriterInMemory(None, Repository.parse(REPOSITORY))


UPSTREAM = Repository.parse("an-upstream-owner/project")
"""
The repository the owner's was forked from.
"""


@dataclass(frozen=True)
class ForkOf(ForkDetails):
    """
    The owner's repository, forked from the repository given.
    """

    forked_from: Repository | None
    """
    The upstream, ``None`` for a repository that is no fork.
    """

    def upstream(self) -> Repository | None:
        return self.forked_from


@dataclass(frozen=True)
class UpstreamReviewsInMemory(UpstreamReviews):
    """
    Answers every request with the threads and reviews given, keeping the requests.
    """

    threads: list[ReviewThread] = field(default_factory=list)
    """
    The upstream pull request's threads.
    """

    reviews: list[Review] = field(default_factory=list)
    """
    Its reviews.
    """

    requests: list[UpstreamReviewRequest] = field(default_factory=list)
    """
    Every request, in order.
    """

    def snapshot(self, request: UpstreamReviewRequest) -> UpstreamPullRequestSnapshot:
        self.requests.append(request)
        return UpstreamPullRequestSnapshot(
            9,
            "A title",
            f"https://github.com/{UPSTREAM}/pull/9",
            self.reviews,
            self.threads,
            None,
        )


def opened_upstream(number: int) -> RestPullRequest:
    """:param number: A pull request.
    :return: It from the work branch, labelled as opened upstream."""
    return replace(
        pull_request(number, "feature"), labels=(UpstreamLabel.OPENED_UPSTREAM,)
    )


def test_unresolved_threads_are_listed_first_by_their_first_comment(
    work: WritePolicy,  # noqa: F811
):
    listing = ReviewThreadListing(
        own(work, pull_request(3, "feature")),
        threads(thread(8, True), thread(9)),
        ForkOf(None),
        UpstreamReviewsInMemory(),
    )

    listed = listing.run().splitlines()

    assert [line.split()[0] for line in listed] == ["9", "8"]


def test_the_upstream_pull_request_s_reviews_and_threads_follow_with_addresses(
    work: WritePolicy,  # noqa: F811
):
    upstream_thread = thread(77)
    review = Review(
        Author("upstream-reviewer"),
        ReviewState.CHANGES_REQUESTED,
        "Rename it.\nPlease.",
        "",
    )
    upstream = UpstreamReviewsInMemory([upstream_thread], [review])
    listing = ReviewThreadListing(
        own(work, opened_upstream(3)), threads(thread(8)), ForkOf(UPSTREAM), upstream
    )

    listed = listing.run().splitlines()

    assert listed[1:] == [
        f"upstream {UPSTREAM}#9 https://github.com/{UPSTREAM}/pull/9:",
        f"review by upstream-reviewer ({ReviewState.CHANGES_REQUESTED}): Rename it.",
        f"{ReviewThreadListing.described(upstream_thread)} "
        f"{upstream_thread.comments[0].url}",
    ]
    assert [(request.upstream, request.branch) for request in upstream.requests] == [
        (UPSTREAM, "feature")
    ]


def test_a_pull_request_not_opened_upstream_reads_nothing_upstream(
    work: WritePolicy,  # noqa: F811
):
    upstream = UpstreamReviewsInMemory([thread(77)])

    ReviewThreadListing(
        own(work, pull_request(3, "feature")), threads(), ForkOf(UPSTREAM), upstream
    ).run()

    assert upstream.requests == []


@dataclass(frozen=True)
class CommentsInMemory(Commenter):
    """
    Records every comment written.
    """

    comments: list[tuple[int, str]] = field(default_factory=list)
    """
    Each comment's pull request and text.
    """

    def add_comment(self, number: int, body: str) -> str:
        self.comments.append((number, body))
        return "https://comment"


def test_an_addressed_upstream_comment_is_linked_on_the_own_pull_request(
    work: WritePolicy,  # noqa: F811
):
    comments = CommentsInMemory()
    address = f"https://github.com/{UPSTREAM}/pull/9#discussion_r77"

    ReviewAddressing(
        own(work, opened_upstream(3)),
        ForkOf(UPSTREAM),
        comments,
        address,
        "Renamed it.",
    ).run()

    assert comments.comments == [(3, f"Addressed upstream: {address}\n\nRenamed it.")]


@pytest.mark.parametrize(
    "forked_from, address",
    [
        (UPSTREAM, "https://github.com/someone-else/project/pull/9#discussion_r77"),
        (None, f"https://github.com/{UPSTREAM}/pull/9#discussion_r77"),
    ],
    ids=["another repository", "no fork"],
)
def test_an_address_not_upstream_is_refused(
    work: WritePolicy, forked_from: Repository | None, address: str  # noqa: F811
):
    comments = CommentsInMemory()

    with pytest.raises(ForeignReviewAddressError):
        ReviewAddressing(
            own(work, opened_upstream(3)), ForkOf(forked_from), comments, address, "x"
        ).run()

    assert comments.comments == []


def test_a_thread_is_replied_to_by_its_first_comment(
    work: WritePolicy,  # noqa: F811
):
    written = writer()

    ReviewReply(
        own(work, pull_request(3, "feature")), threads(thread(9)), written, 9, "Done."
    ).run()

    assert written.written == [f"reply 3 {thread(9).identifier} Done."]


def test_a_thread_the_pull_request_lacks_is_refused(work: WritePolicy):  # noqa: F811
    with pytest.raises(ReviewThreadNotFoundError):
        ReviewReply(
            own(work, pull_request(3, "feature")), threads(thread(9)), writer(), 7, "x"
        ).run()


def test_a_thread_is_resolved_once_the_branch_is_pushed(
    work: WritePolicy,  # noqa: F811
):
    written = writer()

    ReviewResolution(
        own(work, pull_request(3, "feature")), threads(thread(9)), written, 9
    ).run()

    assert written.written == [f"resolve 3 {thread(9).identifier}"]


def test_a_thread_is_not_resolved_while_its_fix_is_unpushed(
    work: WritePolicy,  # noqa: F811
):
    work.checkout.git.run("commit", "--quiet", "--allow-empty", "--message", "Fix")
    written = writer()

    with pytest.raises(UnpushedWorkError):
        ReviewResolution(
            own(work, pull_request(3, "feature")), threads(thread(9)), written, 9
        ).run()

    assert written.written == []


def test_a_resolved_thread_is_left_alone(work: WritePolicy):  # noqa: F811
    written = writer()

    ReviewResolution(
        own(work, pull_request(3, "feature")), threads(thread(9, True)), written, 9
    ).run()

    assert written.written == []
