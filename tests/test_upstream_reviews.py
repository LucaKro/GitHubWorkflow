"""
Tests for :mod:`github_workflow.upstream_reviews`: a request for the reviews of a pull
request opened upstream is queued on the notes branch with the workflow answering it,
answered on the runner with GitHub's recorded answers, and read again from them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from basstler_domain_model.github.clients import GraphQLClient, ReplayingGraphQLClient
from basstler_domain_model.locations import PathEnumeration
from basstler_domain_model.repository import Repository

from github_workflow.exceptions import UpstreamReviewsUnansweredError
from github_workflow.locations import NotesFile
from github_workflow.notes.branch import NotesBranch
from github_workflow.settings import WorkflowSettings
from github_workflow.upstream_reviews import (
    DirectUpstreamReviews,
    ForwardedUpstreamReviews,
    UpstreamReviewAnswering,
    UpstreamReviewKey,
    UpstreamReviewPlaceholder,
    UpstreamReviewRequest,
)

from .repositories_by_owner import RepositoriesByOwner
from .test_discussions import notes_in

# %% GitHub's answers


class UpstreamReviewDataset(PathEnumeration):
    """
    GitHub's answers to reading a pull request opened upstream.
    """

    ANSWERS = (
        Path(__file__).parent / "dataset" / "upstream" / "upstream_review_answers.json"
    )
    """
    The ``data`` of the branch search, then of the one page of threads, in order.
    """

    def answers(self) -> list[dict[str, Any]]:
        """:return: The answers, decoded."""
        return json.loads(self.value.read_text())


@dataclass
class AnswersInOrder(GraphQLClient):
    """
    Answers each query with the next of the answers given.
    """

    answers: list[dict[str, Any]]
    """
    The ``data`` of each answer, in order.
    """

    queries: int = 0
    """
    How many queries were answered.
    """

    def execute(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        self.queries += 1
        return self.answers[self.queries - 1]


def request(name: str = "1.json") -> UpstreamReviewRequest:
    """:param name: The request's file name.
    :return: A request for the reviews upstream of the owner's branch ``feature``."""
    return UpstreamReviewRequest(
        Repository.parse("an-upstream-owner/project"), "LucaKro", "feature", name
    )


# %% reading directly


def test_a_direct_read_finds_the_branch_s_pull_request_upstream():
    snapshot = DirectUpstreamReviews(
        AnswersInOrder(UpstreamReviewDataset.ANSWERS.answers())
    ).snapshot(request())

    assert (snapshot.number, [thread.identifier for thread in snapshot.threads]) == (
        9,
        ["thread-1"],
    )


# %% answering on the runner


def test_a_request_is_answered_with_github_s_answers_and_removed(tmp_path: Path):
    requests, answers = tmp_path / "requests", tmp_path / "answers"
    requests.mkdir()
    (requests / "1.json").write_text(request().to_json())
    recorded = UpstreamReviewDataset.ANSWERS.answers()

    answered = UpstreamReviewAnswering(
        requests, answers, AnswersInOrder(recorded)
    ).run()

    saved = json.loads((answers / "1.json").read_text())
    assert (answered, saved, list(requests.iterdir())) == (
        ["1.json"],
        {UpstreamReviewKey.ANSWERS: recorded},
        [],
    )


def test_the_answers_of_an_earlier_run_are_removed(tmp_path: Path):
    requests, answers = tmp_path / "requests", tmp_path / "answers"
    requests.mkdir()
    answers.mkdir()
    (answers / "0.json").write_text("{}")

    UpstreamReviewAnswering(requests, answers, AnswersInOrder([])).run()

    assert list(answers.iterdir()) == []


def test_an_answer_read_again_gives_what_github_answered():
    recorded = UpstreamReviewDataset.ANSWERS.answers()

    replayed = request().snapshot(ReplayingGraphQLClient(recorded))

    assert replayed == request().snapshot(AnswersInOrder(recorded))


# %% asking through the notes branch


def answered(notes: NotesBranch, name: str) -> None:
    """
    Save GitHub's answers on the notes branch as the runner does.

    :param notes: The notes branch.
    :param name: The request's file name.
    """
    notes.fetch()
    notes.write(
        {
            NotesFile.UPSTREAM_REVIEW_ANSWERS.value
            / name: json.dumps(
                {UpstreamReviewKey.ANSWERS: UpstreamReviewDataset.ANSWERS.answers()}
            )
        },
        "Answer",
    )


def test_a_forwarded_request_is_queued_with_its_workflow(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
):
    notes = notes_in(repositories, owned_url, settings)
    answered(notes, request().name)

    ForwardedUpstreamReviews(notes, timeout_seconds=0).snapshot(request())

    notes.fetch()
    queued = notes.read(NotesFile.UPSTREAM_REVIEW_REQUESTS.value / request().name)
    workflow = notes.read(NotesFile.UPSTREAM_REVIEW_WORKFLOW.value)
    assert (
        queued,
        [
            placeholder
            for placeholder in UpstreamReviewPlaceholder
            if placeholder in workflow
        ],
    ) == (
        request().to_json(),
        [],
    )


def test_a_forwarded_request_reads_the_saved_answer(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
):
    notes = notes_in(repositories, owned_url, settings)
    answered(notes, request().name)

    snapshot = ForwardedUpstreamReviews(notes, timeout_seconds=0).snapshot(request())

    assert snapshot == request().snapshot(
        AnswersInOrder(UpstreamReviewDataset.ANSWERS.answers())
    )


def test_a_request_left_unanswered_is_refused_in_time(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
):
    notes = notes_in(repositories, owned_url, settings)

    with pytest.raises(UpstreamReviewsUnansweredError):
        ForwardedUpstreamReviews(notes, timeout_seconds=0).snapshot(request())
