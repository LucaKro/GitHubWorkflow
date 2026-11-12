"""
Tests for :mod:`domain_model.github.review_writers`: replying to a review thread through
REST, and resolving it through whichever API the place it runs in reaches.
"""

from __future__ import annotations

import json
from http import HTTPStatus

import pytest

from domain_model.environment import ClaudeCodeVariable
from domain_model.github.clients import GitHubApi
from domain_model.github.readers import ReadSource
from domain_model.github.replayed_api import RecordedAnswer, ReplayedApi
from domain_model.github.review_models import Author, ReviewThread, ThreadComment
from domain_model.github.review_writers import (
    GraphQLReviewThreadWriter,
    RestReviewThreadWriter,
)
from domain_model.github.routes import RepositoryRoute
from domain_model.github.vocabulary import QueryVariable, RestJSONKey
from domain_model.repository import Repository

from .test_pull_request_readers import GraphQLAnswersInOrder

REPOSITORY = Repository("an-owner", "a-repository")
"""
The repository every thread here is on.
"""

ROUTE = RepositoryRoute(REPOSITORY)
"""
Its routes.
"""

# %% threads


def thread() -> ReviewThread:
    """:return: An unresolved thread whose first comment is 501."""
    return ReviewThread(
        identifier="PRRT_kwDOthread",
        is_resolved=False,
        is_outdated=False,
        path="src/module.py",
        line=12,
        comments=[
            ThreadComment(
                database_identifier=501,
                author=Author("a-reviewer"),
                body="Name this better.",
                created_at="2026-11-04T10:00:00Z",
                url="https://github.com/an-owner/a-repository/pull/7#discussion_r501",
            )
        ],
    )


# %% replying


def test_a_thread_is_replied_to_under_its_first_comment():
    replies = f"/{ROUTE.review_comment_replies(7, 501)}"
    answers = {
        ("POST", replies): RecordedAnswer(
            HTTPStatus.CREATED, json.dumps({RestJSONKey.HTML_URL: "https://reply"})
        )
    }

    with ReplayedApi(answers) as api:
        writer = RestReviewThreadWriter(GitHubApi("a-token", api.url), REPOSITORY)
        writer.reply(7, thread(), "Renamed it in the next commit.")

    assert [(sent.method, sent.path, sent.payload) for sent in api.sent] == [
        ("POST", replies, {RestJSONKey.BODY: "Renamed it in the next commit."})
    ]


# %% resolving


def test_a_thread_is_resolved_through_the_session_proxy_s_route():
    resolution = f"/{ROUTE.thread_resolution(7, 501)}"
    answers = {("POST", resolution): RecordedAnswer(HTTPStatus.OK, "{}")}

    with ReplayedApi(answers) as api:
        RestReviewThreadWriter(GitHubApi("a-token", api.url), REPOSITORY).resolve(
            7, thread()
        )

    assert [(sent.method, sent.path) for sent in api.sent] == [("POST", resolution)]


def test_a_thread_is_resolved_through_graphql_by_its_node_identifier():
    graphql = GraphQLAnswersInOrder([{"resolveReviewThread": {"thread": {}}}])

    with ReplayedApi({}) as api:
        GraphQLReviewThreadWriter(
            GitHubApi("a-token", api.url), REPOSITORY, graphql
        ).resolve(7, thread())

    assert graphql.variables_sent == [{QueryVariable.THREAD_ID: thread().identifier}]


# %% choosing


def test_a_cloud_session_resolves_through_rest_and_any_other_place_through_graphql(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = GitHubApi("a-token", "https://api.example")
    monkeypatch.setenv(ClaudeCodeVariable.REMOTE, "true")
    in_a_cloud_session = ReadSource.detect().writer(api, REPOSITORY)
    monkeypatch.delenv(ClaudeCodeVariable.REMOTE)
    elsewhere = ReadSource.detect().writer(api, REPOSITORY)

    assert [type(in_a_cloud_session), type(elsewhere)] == [
        RestReviewThreadWriter,
        GraphQLReviewThreadWriter,
    ]
