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
from basstler_domain_model.github.review_writers import ReviewThreadWriter
from basstler_domain_model.github.readers import PullRequestSource
from basstler_domain_model.github.vocabulary import PullRequestState
from basstler_domain_model.repository import Repository

from github_workflow.exceptions import (
    NoOpenPullRequestError,
    NothingToLabelError,
    ReviewThreadNotFoundError,
    UnknownLabelError,
    UnpushedWorkError,
)
from github_workflow.own_pull_request import (
    PullRequestLabelling,
    ReviewReply,
    ReviewResolution,
    ReviewThreadListing,
    WorkBranchPullRequest,
)
from github_workflow.policy import WritePolicy

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


def test_unresolved_threads_are_listed_first_by_their_first_comment(
    work: WritePolicy,  # noqa: F811
):
    listing = ReviewThreadListing(
        own(work, pull_request(3, "feature")), threads(thread(8, True), thread(9))
    )

    listed = listing.run().splitlines()

    assert [line.split()[0] for line in listed] == ["9", "8"]


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
