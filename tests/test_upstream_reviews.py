"""
Tests for :mod:`github_workflow.upstream_reviews`: a request for the reviews of a pull
request opened upstream is queued on the notes branch with the workflow answering it,
answered on the runner with GitHub's recorded answers, and read again from them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from domain_model.git.revisions import BranchName, TextFiles
from domain_model.github.clients import (
    GraphQLClient,
    RecordedAnswers,
    ReplayingGraphQLClient,
)
from domain_model.github.repository_client import RepositoryWorkflows
from domain_model.github.rest_models import Workflow, WorkflowRun
from domain_model.github.vocabulary import (
    WorkflowRunConclusion,
    WorkflowRunStatus,
)
from domain_model.locations import PathEnumeration
from domain_model.repository import Repository

from github_workflow.locations import NotesFile
from github_workflow.notes.branch import NotesBranch
from github_workflow.settings import WorkflowSettings
from github_workflow.upstream_reviews import (
    DirectUpstreamReviews,
    ForwardedUpstreamReviews,
    UpstreamReadFailed,
    UpstreamReadNotStarted,
    UpstreamReadUnanswered,
    UpstreamReviewAnswering,
    UpstreamReviewRequest,
)
from github_workflow.workflow_templates import (
    ActionPlaceholder,
    NotesBranchPlaceholder,
    UpstreamReviewPlaceholder,
)

from .repositories_by_owner import RepositoriesByOwner
from .scratch_github import ScratchGitHub
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


def test_a_direct_read_finds_the_branch_s_pull_request_upstream() -> None:
    snapshot = DirectUpstreamReviews(
        AnswersInOrder(UpstreamReviewDataset.ANSWERS.answers())
    ).snapshot(request())

    assert (snapshot.number, [thread.identifier for thread in snapshot.threads]) == (
        9,
        ["thread-1"],
    )


# %% answering on the runner


def test_a_request_is_answered_with_github_s_answers_and_removed(
    tmp_path: Path,
) -> None:
    requests, answers = tmp_path / "requests", tmp_path / "answers"
    requests.mkdir()
    (requests / "1.json").write_text(request().to_json())
    recorded = UpstreamReviewDataset.ANSWERS.answers()

    answered = UpstreamReviewAnswering(
        requests, answers, AnswersInOrder(recorded)
    ).run()

    saved = RecordedAnswers.from_json((answers / "1.json").read_text())
    assert (answered, saved, list(requests.iterdir())) == (
        ["1.json"],
        RecordedAnswers(recorded),
        [],
    )


def test_the_answers_of_an_earlier_run_are_removed(tmp_path: Path) -> None:
    requests, answers = tmp_path / "requests", tmp_path / "answers"
    requests.mkdir()
    answers.mkdir()
    (answers / "0.json").write_text("{}")

    UpstreamReviewAnswering(requests, answers, AnswersInOrder([])).run()

    assert list(answers.iterdir()) == []


def test_an_answer_read_again_gives_what_github_answered() -> None:
    recorded = UpstreamReviewDataset.ANSWERS.answers()

    replayed = request().snapshot(ReplayingGraphQLClient(RecordedAnswers(recorded)))

    assert replayed == request().snapshot(AnswersInOrder(recorded))


# %% asking through the notes branch


@dataclass(frozen=True)
class RunsOfTheQueuedRequest(RepositoryWorkflows):
    """
    The fork's runs on the notes branch: one of the reading workflow, on the notes
    branch's newest commit, as given, or none.
    """

    notes: NotesBranch
    """
    The notes branch.
    """

    status: WorkflowRunStatus | None = None
    """
    Where the run stands, ``None`` for no run.
    """

    conclusion: WorkflowRunConclusion | None = None
    """
    How it ended, ``None`` until it did.
    """

    def workflows(self) -> list[Workflow]:
        return []

    def branch_runs(self, branch: BranchName) -> list[WorkflowRun]:
        if self.status is None:
            return []
        tip = self.notes.branch.remote.git.run(
            "rev-parse", self.notes.branch.tracking_branch.revision_name
        )
        return [
            WorkflowRun(
                1,
                str(NotesFile.UPSTREAM_REVIEW_WORKFLOW.value),
                tip,
                self.status,
                self.conclusion,
                ScratchGitHub.owned.workflow_run_url(1),
            )
        ]


def forwarded(
    notes: NotesBranch, runs: RunsOfTheQueuedRequest | None = None
) -> ForwardedUpstreamReviews:
    """
    :param notes: The fork's notes branch.
    :param runs: The fork's runs, none when left out.
    :return: Reviews read through the fork's Actions, given up on at once.
    """
    return ForwardedUpstreamReviews(
        notes,
        ScratchGitHub.owned,
        runs or RunsOfTheQueuedRequest(notes),
        timeout_seconds=0,
        start_seconds=0,
    )


def answered(notes: NotesBranch, name: str) -> None:
    """
    Save GitHub's answers on the notes branch as the runner does.

    :param notes: The notes branch.
    :param name: The request's file name.
    """
    notes.fetch()
    notes.write(
        TextFiles(
            {
                NotesFile.UPSTREAM_REVIEW_ANSWERS.value
                / name: RecordedAnswers(
                    UpstreamReviewDataset.ANSWERS.answers()
                ).to_json()
            }
        ),
        "Answer",
    )


def test_a_forwarded_request_is_queued_with_its_workflow(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
) -> None:
    notes = notes_in(repositories, owned_url, settings)
    answered(notes, request().name)

    forwarded(notes).snapshot(request())

    notes.fetch()
    queued = notes.read(NotesFile.UPSTREAM_REVIEW_REQUESTS.value / request().name)
    workflow = notes.read(NotesFile.UPSTREAM_REVIEW_WORKFLOW.value)
    assert (
        queued,
        [
            placeholder
            for kind in (
                NotesBranchPlaceholder,
                UpstreamReviewPlaceholder,
                ActionPlaceholder,
            )
            for placeholder in kind
            if placeholder in workflow
        ],
    ) == (
        request().to_json(),
        [],
    )


def test_a_forwarded_request_reads_the_saved_answer(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
) -> None:
    notes = notes_in(repositories, owned_url, settings)
    answered(notes, request().name)

    snapshot = forwarded(notes).snapshot(request())

    assert snapshot == request().snapshot(
        AnswersInOrder(UpstreamReviewDataset.ANSWERS.answers())
    )


def queued_requests(notes: NotesBranch) -> list[str]:
    """:param notes: The notes branch.
    :return: The names of the requests waiting on it."""
    notes.fetch()
    listed = notes.branch.remote.git.run(
        "ls-tree",
        "--name-only",
        f"{notes.branch.tracking_branch.revision_name}:{NotesFile.UPSTREAM_REVIEW_REQUESTS.value}",
    )
    return listed.split()


def test_a_request_no_run_started_for_is_asked_again_then_given_up_on(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
) -> None:
    notes = notes_in(repositories, owned_url, settings)

    unavailable = forwarded(notes).snapshot(request())

    assert (unavailable, len(queued_requests(notes))) == (
        UpstreamReadNotStarted(ScratchGitHub.owned, 0),
        2,
    )


def test_a_request_whose_run_failed_is_given_up_on(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
) -> None:
    notes = notes_in(repositories, owned_url, settings)
    failed = RunsOfTheQueuedRequest(
        notes, WorkflowRunStatus.COMPLETED, WorkflowRunConclusion.FAILURE
    )

    unavailable = forwarded(notes, failed).snapshot(request())

    assert unavailable == UpstreamReadFailed(
        ScratchGitHub.owned.workflow_run_url(1), WorkflowRunConclusion.FAILURE
    )


def test_a_request_whose_run_is_still_going_is_left_unanswered_in_time(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
) -> None:
    notes = notes_in(repositories, owned_url, settings)
    going = RunsOfTheQueuedRequest(notes, WorkflowRunStatus.IN_PROGRESS)

    unavailable = forwarded(notes, going).snapshot(request())

    assert unavailable == UpstreamReadUnanswered(request().upstream, 0)
