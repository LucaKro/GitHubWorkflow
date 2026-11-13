"""
Tests for :mod:`domain_model.github.conversations`: conversations read as every text
written in them, the texts an account wrote mentioning itself, and the searches finding
the conversations holding them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from domain_model.github.clients import GitHubReader
from domain_model.github.conversations import (
    ConversationAddress,
    ConversationKind,
    ConversationReader,
    SelfMention,
    SelfMentionSearch,
)
from domain_model.github.exceptions import MalformedConversationUrlError
from domain_model.github.routes import RepositoryRoute
from domain_model.github.vocabulary import (
    PullRequestJSONKey,
    QueryParameter,
    QueryVariable,
    SearchQualifier,
)
from domain_model.repository import Repository

from .dataset.locations import DatasetLocation

# %% GitHub's answers


@dataclass
class ConversationAnswers(GitHubReader):
    """
    Answers the reads of one pull request and one discussion with their recordings,
    every issue search with one page and every discussion search with one page, and
    keeps each search query asked.
    """

    searched: list[str] = field(default_factory=list)
    """
    Every search query asked, in order.
    """

    def get(self, path: str) -> Any:
        return self.rest_answers()[path]

    def get_pages(self, path: str) -> list[Any]:
        if path.startswith("search/"):
            self.searched += parse_qs(urlsplit(path).query)[QueryParameter.SEARCH]
            return [json.loads(DatasetLocation.ISSUE_SEARCH.read_text())]
        return [self.rest_answers()[path]]

    def execute(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        if QueryVariable.SEARCH in variables:
            self.searched.append(variables[QueryVariable.SEARCH])
            return json.loads(DatasetLocation.DISCUSSION_SEARCH.read_text())
        page = (
            DatasetLocation.DISCUSSION_PAGE_ONE
            if variables[QueryVariable.COMMENT_CURSOR] is None
            else DatasetLocation.DISCUSSION_PAGE_TWO
        )
        return json.loads(page.read_text())

    @staticmethod
    def rest_answers() -> dict[str, Any]:
        """:return: The answer to each REST path reading the pull request."""
        route = RepositoryRoute(PULL_REQUEST.repository)
        number = PULL_REQUEST.number
        return {
            route.issue(number): json.loads(
                DatasetLocation.CONVERSATION_PULL_REQUEST.read_text()
            ),
            route.listing(route.issue_comments(number)): json.loads(
                DatasetLocation.CONVERSATION_ISSUE_COMMENTS.read_text()
            ),
            route.reviews(number): json.loads(
                DatasetLocation.CONVERSATION_REVIEWS.read_text()
            ),
            route.review_comments(number): json.loads(
                DatasetLocation.CONVERSATION_REVIEW_COMMENTS.read_text()
            ),
        }


LOGIN = "an-owner"
"""
The account mentioning itself in the recordings.
"""

PULL_REQUEST = ConversationAddress(
    Repository("an-upstream", "a-repository"), ConversationKind.PULL_REQUEST, 5
)
"""
The recorded pull request.
"""

DISCUSSION = ConversationAddress(
    Repository("an-upstream", "a-repository"), ConversationKind.DISCUSSION, 7
)
"""
The recorded discussion.
"""


def urls_of_self_mentions(address: ConversationAddress) -> list[str]:
    """
    :param address: A recorded conversation.
    :return: The page of every text in it :data:`LOGIN` wrote mentioning itself.
    """
    conversation = ConversationReader(ConversationAnswers()).read(address)
    return [comment.url for comment in conversation.self_mentions(LOGIN)]


# %% addresses


def test_a_comment_s_page_names_its_conversation() -> None:
    url = f"{PULL_REQUEST.url}#issuecomment-102"

    assert ConversationAddress.from_url(url) == PULL_REQUEST


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/an-upstream/a-repository",
        "https://github.com/an-upstream/a-repository/commit/5",
        "https://example.com/an-upstream/a-repository/pull/5",
        "https://github.com/an-upstream/a-repository/pull/five",
    ],
)
def test_a_page_of_no_conversation_is_refused(url: str) -> None:
    with pytest.raises(MalformedConversationUrlError):
        ConversationAddress.from_url(url)


# %% reading a conversation


def test_a_pull_request_s_self_mentions_come_from_every_text_written_in_it() -> None:
    assert urls_of_self_mentions(PULL_REQUEST) == [
        PULL_REQUEST.url,
        f"{PULL_REQUEST.url}#issuecomment-102",
        f"{PULL_REQUEST.url}#pullrequestreview-201",
        f"{PULL_REQUEST.url}#discussion_r301",
    ]


def test_a_pending_review_is_not_read() -> None:
    conversation = ConversationReader(ConversationAnswers()).read(PULL_REQUEST)

    assert f"{PULL_REQUEST.url}#pullrequestreview-202" not in [
        comment.url for comment in conversation.comments
    ]


def test_a_deleted_account_s_comment_is_written_by_nobody() -> None:
    conversation = ConversationReader(ConversationAnswers()).read(PULL_REQUEST)

    deleted = next(
        comment
        for comment in conversation.comments
        if comment.url == f"{PULL_REQUEST.url}#issuecomment-103"
    )
    assert deleted.author is None


def test_a_discussion_s_self_mentions_come_from_every_page_and_reply() -> None:
    assert urls_of_self_mentions(DISCUSSION) == [
        f"{DISCUSSION.url}#discussioncomment-402",
        f"{DISCUSSION.url}#discussioncomment-403",
    ]


def test_a_discussion_is_read_with_its_title() -> None:
    conversation = ConversationReader(ConversationAnswers()).read(DISCUSSION)

    recorded = json.loads(DatasetLocation.DISCUSSION_PAGE_ONE.read_text())
    assert (
        conversation.title
        == recorded[PullRequestJSONKey.REPOSITORY][PullRequestJSONKey.DISCUSSION][
            PullRequestJSONKey.TITLE
        ]
    )


def test_self_mentions_across_conversations_are_listed_oldest_first() -> None:
    reader = ConversationReader(ConversationAnswers())
    conversations = [reader.read(DISCUSSION), reader.read(PULL_REQUEST)]

    mentions = SelfMention.every_mention(conversations, LOGIN)

    assert [mention.comment.url for mention in mentions] == [
        PULL_REQUEST.url,
        f"{PULL_REQUEST.url}#discussion_r301",
        f"{PULL_REQUEST.url}#issuecomment-102",
        f"{PULL_REQUEST.url}#pullrequestreview-201",
        f"{DISCUSSION.url}#discussioncomment-402",
        f"{DISCUSSION.url}#discussioncomment-403",
    ]


# %% searching


def test_the_issue_searches_find_each_conversation_once_in_order() -> None:
    found = SelfMentionSearch(ConversationAnswers(), LOGIN, None).issue_conversations()

    assert found == [
        ConversationAddress(Repository(LOGIN, "a-fork"), ConversationKind.ISSUE, 3),
        PULL_REQUEST,
    ]


def test_the_issue_searches_look_where_the_account_opened_commented_or_reviewed() -> (
    None
):
    answers = ConversationAnswers()

    SelfMentionSearch(answers, LOGIN, None).issue_conversations()

    assert answers.searched == [
        f"is:issue mentions:{LOGIN} author:{LOGIN}",
        f"is:issue mentions:{LOGIN} commenter:{LOGIN}",
        f"is:pull-request mentions:{LOGIN} author:{LOGIN}",
        f"is:pull-request mentions:{LOGIN} commenter:{LOGIN}",
        f"is:pull-request mentions:{LOGIN} reviewed-by:{LOGIN}",
    ]


def test_the_discussion_searches_find_each_discussion_once() -> None:
    assert SelfMentionSearch(ConversationAnswers(), LOGIN, None).discussions() == [
        DISCUSSION
    ]


def test_a_search_since_a_time_leaves_out_what_did_not_change_since_in_utc() -> None:
    answers = ConversationAnswers()
    since = datetime(2026, 11, 13, 10, 30, tzinfo=timezone.utc)

    SelfMentionSearch(answers, LOGIN, since).discussions()

    assert answers.searched[0].split()[-1] == SearchQualifier.UPDATED.narrowing(
        ">=2026-11-13T10:30:00Z"
    )
