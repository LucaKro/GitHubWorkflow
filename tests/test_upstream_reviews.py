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

from domain_model.code_version import CodeVersion
from domain_model.git.revisions import BranchName, CommitHash, TextFiles
from domain_model.github.answer_recording import (
    AnswerRecording,
    RecordingClient,
    ReplayingClient,
)
from domain_model.github.clients import GitHubReader
from domain_model.github.repository_client import RepositoryWorkflows
from domain_model.github.rest_models import Workflow, WorkflowRun
from domain_model.github.routes import RepositoryRoute
from domain_model.github.vocabulary import (
    RestJSONKey,
    WorkflowRunConclusion,
    WorkflowRunStatus,
)
from domain_model.locations import PathEnumeration
from domain_model.repository import Repository

from github_workflow.exceptions import (
    ForwardedAnswerUnreadable,
    ForwardedReadFailed,
    ForwardedReadNotStarted,
    ForwardedReadUnanswered,
)
from github_workflow.forwarded_reads import (
    ForwardedAnswer,
    ForwardedAnswerKey,
    ForwardedReadAnswering,
)
from github_workflow.locations import NotesFile
from github_workflow.notes.branch import NotesBranch
from github_workflow.settings import WorkflowSettings
from github_workflow.upstream_reviews import (
    DirectUpstreamReviews,
    ForwardedUpstreamReviews,
    UpstreamReviewRequest,
)
from github_workflow.workflow_templates import (
    ActionPlaceholder,
    ForwardedReadPlaceholder,
    ForwardedSubject,
    NotesBranchPlaceholder,
)

from .repositories_by_owner import RepositoriesByOwner
from .scratch_github import ScratchGitHub
from .test_discussions import clone_notes_branch

# %% GitHub's answers


class UpstreamReviewDataset(PathEnumeration):
    """
    GitHub's answers to reading a pull request opened upstream.
    """

    PULL_REQUEST = Path(__file__).parent / "dataset" / "upstream" / "pull-request.json"
    """
    The pull request, as REST reads it on its own and lists it for its head branch.
    """

    REVIEWS = Path(__file__).parent / "dataset" / "upstream" / "reviews.json"
    """
    The one page of its reviews.
    """

    CHECK_RUNS = Path(__file__).parent / "dataset" / "upstream" / "check-runs.json"
    """
    The one page of the check runs on its head commit, which has none.
    """

    STATUSES = Path(__file__).parent / "dataset" / "upstream" / "statuses.json"
    """
    The one page of the commit statuses on its head commit, which has none.
    """

    THREADS_PAGE = Path(__file__).parent / "dataset" / "upstream" / "threads-page.json"
    """
    The ``data`` of the one page of its review threads.
    """

    def decode_answer(self) -> Any:
        """:return: The answer, decoded."""
        return json.loads(self.value.read_text())


@dataclass(frozen=True)
class UpstreamAnswers(GitHubReader):
    """
    Answers each REST path the reads of the upstream pull request take with its recorded
    answer, and every GraphQL query with its one page of threads.
    """

    def get(self, path: str) -> Any:
        return self.rest_answers()[path]

    def get_pages(self, path: str) -> list[Any]:
        return self.rest_answers()[path]

    def execute(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        return UpstreamReviewDataset.THREADS_PAGE.decode_answer()

    @staticmethod
    def rest_answers() -> dict[str, Any]:
        """:return: The answer to each REST path, pages listed for a paged one."""
        asked = request()
        route = RepositoryRoute(asked.upstream)
        pull_request = UpstreamReviewDataset.PULL_REQUEST.decode_answer()
        number = pull_request[RestJSONKey.NUMBER]
        commit = pull_request[RestJSONKey.HEAD][RestJSONKey.SHA]
        return {
            route.pull_requests_for_head(asked.fork_owner, asked.branch): [
                [pull_request]
            ],
            route.pull_request(number): pull_request,
            route.reviews(number): [UpstreamReviewDataset.REVIEWS.decode_answer()],
            route.check_runs(commit): [
                UpstreamReviewDataset.CHECK_RUNS.decode_answer()
            ],
            route.commit_status(commit): [
                UpstreamReviewDataset.STATUSES.decode_answer()
            ],
        }


def recorded_answers() -> AnswerRecording:
    """:return: GitHub's answers to the reads of :func:`request`, recorded."""
    recording = RecordingClient(UpstreamAnswers())
    request().read(recording)
    return recording.recording


def request(name: str = "1.json") -> UpstreamReviewRequest:
    """:param name: The request's file name.
    :return: A request for the reviews upstream of the owner's branch ``feature``."""
    return UpstreamReviewRequest(
        Repository.parse("an-upstream-owner/project"),
        "LucaKro",
        BranchName("feature"),
        name=name,
    )


# %% reading directly


def test_a_direct_read_finds_the_branch_s_pull_request_upstream() -> None:
    snapshot = DirectUpstreamReviews(UpstreamAnswers()).read(request())

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
    (requests / "1.json").write_text(json.dumps(request().to_json()))

    answered = ForwardedReadAnswering(
        UpstreamReviewRequest, requests, answers, UpstreamAnswers()
    ).run()

    saved = json.loads((answers / "1.json").read_text())
    recording = AnswerRecording.from_json(
        json.dumps(saved[ForwardedAnswerKey.RECORDING])
    )
    assert (
        answered,
        saved[ForwardedAnswerKey.REQUEST],
        recording,
        list(requests.iterdir()),
    ) == (["1.json"], request().to_json(), recorded_answers(), [])


def test_the_answers_of_an_earlier_run_are_removed(tmp_path: Path) -> None:
    requests, answers = tmp_path / "requests", tmp_path / "answers"
    requests.mkdir()
    answers.mkdir()
    (answers / "0.json").write_text("{}")

    ForwardedReadAnswering(
        UpstreamReviewRequest, requests, answers, UpstreamAnswers()
    ).run()

    assert list(answers.iterdir()) == []


def test_an_answer_read_again_gives_what_github_answered() -> None:
    replayed = request().read(ReplayingClient(recorded_answers()))

    assert replayed == request().read(UpstreamAnswers())


def test_an_answer_lacking_a_read_is_unavailable_with_both_versions() -> None:
    recorder = CodeVersion("0.2.0", CommitHash("1" * 40))
    lacking = ForwardedAnswer(request(), AnswerRecording(recorder)).to_json()

    unavailable = ForwardedAnswer.replay(lacking, UpstreamReviewRequest, "1.json")

    assert isinstance(unavailable, ForwardedAnswerUnreadable)
    assert (unavailable.recorder, unavailable.replayer) == (
        recorder,
        CodeVersion.from_installation(),
    )


def test_an_answer_saved_in_the_old_form_is_unavailable() -> None:
    unavailable = ForwardedAnswer.replay(
        json.dumps({"answers": []}), UpstreamReviewRequest, "1.json"
    )

    assert isinstance(unavailable, ForwardedAnswerUnreadable)
    assert unavailable.recorder is None


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


def build_forwarded_reviews(
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


def save_answers(notes: NotesBranch, name: str) -> None:
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
                / name: ForwardedAnswer(request(name), recorded_answers()).to_json()
            }
        ),
        "Answer",
    )


def test_a_forwarded_request_is_queued_with_its_workflow(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
) -> None:
    notes = clone_notes_branch(repositories, owned_url, settings)
    save_answers(notes, request().name)

    build_forwarded_reviews(notes).read(request())

    notes.fetch()
    queued = notes.read(NotesFile.UPSTREAM_REVIEW_REQUESTS.value / request().name)
    workflow = notes.read(NotesFile.UPSTREAM_REVIEW_WORKFLOW.value)
    assert (
        queued,
        [
            placeholder
            for kind in (
                NotesBranchPlaceholder,
                ForwardedReadPlaceholder,
                ActionPlaceholder,
            )
            for placeholder in kind
            if placeholder in workflow
        ],
    ) == (
        json.dumps(request().to_json(), indent=2),
        [],
    )


def test_a_forwarded_request_reads_the_saved_answer(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
) -> None:
    notes = clone_notes_branch(repositories, owned_url, settings)
    save_answers(notes, request().name)

    snapshot = build_forwarded_reviews(notes).read(request())

    assert snapshot == request().read(UpstreamAnswers())


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
    notes = clone_notes_branch(repositories, owned_url, settings)

    unavailable = build_forwarded_reviews(notes).read(request())

    assert (unavailable, len(queued_requests(notes))) == (
        ForwardedReadNotStarted(
            ForwardedSubject.UPSTREAM_REVIEWS, ScratchGitHub.owned, 0
        ),
        2,
    )


def test_a_request_whose_run_failed_is_given_up_on(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
) -> None:
    notes = clone_notes_branch(repositories, owned_url, settings)
    failed = RunsOfTheQueuedRequest(
        notes, WorkflowRunStatus.COMPLETED, WorkflowRunConclusion.FAILURE
    )

    unavailable = build_forwarded_reviews(notes, failed).read(request())

    assert unavailable == ForwardedReadFailed(
        ForwardedSubject.UPSTREAM_REVIEWS,
        ScratchGitHub.owned.workflow_run_url(1),
        WorkflowRunConclusion.FAILURE,
    )


def test_a_request_whose_run_is_still_going_is_left_unanswered_in_time(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
) -> None:
    notes = clone_notes_branch(repositories, owned_url, settings)
    going = RunsOfTheQueuedRequest(notes, WorkflowRunStatus.IN_PROGRESS)

    unavailable = build_forwarded_reviews(notes, going).read(request())

    assert unavailable == ForwardedReadUnanswered(
        ForwardedSubject.UPSTREAM_REVIEWS, ScratchGitHub.owned, 0
    )
