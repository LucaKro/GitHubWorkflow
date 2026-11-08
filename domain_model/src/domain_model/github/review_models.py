"""
Models of a pull request's reviews and review threads, as GitHub's GraphQL API returns
them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from domain_model.class_property import (
    classproperty,
)
from domain_model.github.vocabulary import (
    JSONModel,
    PullRequestJSONKey,
    PullRequestState,
    RestJSONKey,
    ReviewState,
    ThreadMarker,
)

# %% models mirroring the data


@dataclass(frozen=True)
class Author(JSONModel):
    """
    Whoever wrote a comment or submitted a review.
    """

    login: str
    """
    Their GitHub login, or a placeholder when the account is gone.
    """

    @classproperty
    def unknown_login(cls) -> str:
        """
        Stands in for the author of a comment whose account no longer exists.
        """
        return "(unknown)"

    @classmethod
    def from_json(cls, data: dict[str, Any] | None) -> Author:
        """
        Read an author, tolerating the null GitHub returns for deleted users.

        :param data: The ``author`` object, which GitHub may report as null.
        :return: The parsed author.
        """
        if data is None:
            return cls(cls.unknown_login)
        return cls(data[PullRequestJSONKey.LOGIN])

    def has_login(self, login: str) -> bool:
        """
        :param login: A GitHub login, in any case.
        :return: Whether it is this author's login, which GitHub matches regardless of
            case.
        """
        return self.login.casefold() == login.casefold()


@dataclass(frozen=True)
class ThreadComment(JSONModel):
    """
    One comment inside a review thread.
    """

    database_identifier: int
    """
    GitHub's numeric identifier, the one that appears in comment permalinks.
    """

    author: Author
    """
    Whoever wrote the comment.
    """

    body: str
    """
    The comment text, exactly as written.
    """

    created_at: str
    """
    When the comment was posted, as an ISO 8601 timestamp.
    """

    url: str
    """
    The permalink to this comment.
    """

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> ThreadComment:
        """
        Build a comment from one ``comments`` node.

        :param data: The node to read.
        :return: The parsed comment.
        """
        return cls(
            database_identifier=data[PullRequestJSONKey.DATABASE_IDENTIFIER],
            author=Author.from_json(data[PullRequestJSONKey.AUTHOR]),
            body=data[PullRequestJSONKey.BODY],
            created_at=data[PullRequestJSONKey.CREATED_AT],
            url=data[PullRequestJSONKey.URL],
        )

    @classmethod
    def from_rest_json(cls, data: dict[str, Any]) -> ThreadComment:
        """
        Read a review comment as REST lists every comment on a pull request.

        :param data: The comment object.
        :return: The parsed comment.
        """
        return cls(
            database_identifier=data[RestJSONKey.IDENTIFIER],
            author=Author.from_json(data[RestJSONKey.USER]),
            body=data[RestJSONKey.BODY],
            created_at=data[RestJSONKey.CREATED_AT],
            url=data[RestJSONKey.HTML_URL],
        )


@dataclass(frozen=True)
class ReviewThread(JSONModel):
    """
    A conversation anchored to one location in the pull request's diff.
    """

    identifier: str
    """
    GitHub's node identifier for the thread.
    """

    is_resolved: bool
    """
    Whether a reviewer has marked the thread resolved.
    """

    is_outdated: bool
    """
    Whether the diff hunk the thread was anchored to has since changed.
    """

    path: str
    """
    The file the thread is attached to.
    """

    line: int | None
    """
    The line the thread is attached to, absent once the hunk is outdated.
    """

    comments: list[ThreadComment]
    """
    Every comment in the thread, oldest first.
    """

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> ReviewThread:
        """
        Build a thread from one ``reviewThreads`` node.

        :param data: The node to read.
        :return: The parsed thread.
        """
        return cls(
            identifier=data[PullRequestJSONKey.IDENTIFIER],
            is_resolved=data[PullRequestJSONKey.IS_RESOLVED],
            is_outdated=data[PullRequestJSONKey.IS_OUTDATED],
            path=data[PullRequestJSONKey.PATH],
            line=data[PullRequestJSONKey.LINE],
            comments=PullRequestJSONKey.COMMENTS.read_list(data, ThreadComment),
        )

    @property
    def location(self) -> str:
        """:return: The thread's ``path:line``, or just its path when it is outdated."""
        if self.line is None:
            return self.path
        return f"{self.path}:{self.line}"

    @property
    def markers(self) -> list[ThreadMarker]:
        """:return: The annotations this thread carries."""
        carried = []
        if self.is_resolved:
            carried.append(ThreadMarker.RESOLVED)
        if self.is_outdated:
            carried.append(ThreadMarker.OUTDATED)
        return carried


@dataclass(frozen=True)
class Review(JSONModel):
    """
    A submitted review, separate from the threads it may have opened.
    """

    author: Author
    """
    Whoever submitted the review.
    """

    state: ReviewState
    """
    The verdict the reviewer submitted.
    """

    body: str
    """
    The review's summary text, which is often empty.
    """

    submitted_at: str
    """
    When the review was submitted, as an ISO 8601 timestamp.
    """

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Review:
        """
        Build a review from one ``reviews`` node.

        :param data: The node to read.
        :return: The parsed review.
        """
        return cls(
            author=Author.from_json(data[PullRequestJSONKey.AUTHOR]),
            state=ReviewState.from_name(data[PullRequestJSONKey.STATE]),
            body=data[PullRequestJSONKey.BODY],
            submitted_at=data[PullRequestJSONKey.SUBMITTED_AT],
        )

    @classmethod
    def from_rest_json(cls, data: dict[str, Any]) -> Review:
        """
        Read a review as REST lists it, whose body and submission time are null until
        submitted.

        :param data: The review object.
        :return: The parsed review.
        """
        return cls(
            author=Author.from_json(data[RestJSONKey.USER]),
            state=ReviewState.from_name(data[RestJSONKey.STATE]),
            body=data[RestJSONKey.BODY] or "",
            submitted_at=data[RestJSONKey.SUBMITTED_AT] or "",
        )


@dataclass(frozen=True)
class BranchPullRequest(JSONModel):
    """
    One pull request found by searching the upstream for a head branch.
    """

    number: int
    """
    Its number on the upstream repository.
    """

    state: PullRequestState
    """
    Its lifecycle state.
    """

    head_owner: Author
    """
    The owner of the repository the head branch lives in.
    """

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> BranchPullRequest:
        """
        Build a summary from one ``pullRequests`` node.

        :param data: The node to read.
        :return: The parsed summary.
        """
        return cls(
            number=data[PullRequestJSONKey.NUMBER],
            state=PullRequestState.from_name(data[PullRequestJSONKey.STATE]),
            head_owner=Author.from_json(data[PullRequestJSONKey.HEAD_REPOSITORY_OWNER]),
        )


@dataclass(frozen=True)
class PageInfo(JSONModel):
    """
    Where one page of a paged list stands in the whole list.
    """

    has_next_page: bool
    """
    Whether another page follows.
    """

    end_cursor: str | None
    """
    The cursor to request that next page with.
    """

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> PageInfo:
        """
        Read a ``pageInfo`` object.

        :param data: The object to read.
        :return: The parsed page position.
        """
        return cls(
            has_next_page=data[PullRequestJSONKey.HAS_NEXT_PAGE],
            end_cursor=data[PullRequestJSONKey.END_CURSOR],
        )


@dataclass(frozen=True)
class ReviewThreadPage(JSONModel):
    """
    One page of review threads, with where it stands in the whole list.
    """

    threads: list[ReviewThread]
    """
    The threads on this page.
    """

    page_info: PageInfo
    """
    Whether another page follows, and the cursor to request it with.
    """

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> ReviewThreadPage:
        """
        Build a page from a ``reviewThreads`` object.

        :param data: The object to read.
        :return: The parsed page.
        """
        return cls(
            threads=[
                ReviewThread.from_json(node) for node in data[PullRequestJSONKey.NODES]
            ],
            page_info=PageInfo.from_json(data[PullRequestJSONKey.PAGE_INFO]),
        )
