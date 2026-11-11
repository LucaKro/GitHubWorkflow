"""
The reviews of a fork's pull request opened upstream, read directly where the upstream
is reached, and otherwise by the fork's Actions, which answer a request queued on the
notes branch with GitHub's answers saved there. Nothing is ever written upstream.

Usage on the runner: ``python -m github_workflow.upstream_reviews <requests directory>
<answers directory>``; answers every waiting request and removes it.
"""

from __future__ import annotations

import argparse
import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Any

from domain_model.github.clients import (
    GitHubApi,
    GraphQLClient,
    RecordingGraphQLClient,
    ReplayingGraphQLClient,
)
from domain_model.github.pull_request_models import (
    UpstreamPullRequestSnapshot,
)
from domain_model.github.readers import UpstreamPullRequestReader
from domain_model.github.repository_client import RepositoryWorkflows
from domain_model.github.vocabulary import WorkflowRunConclusion
from domain_model.repository import Repository

from github_workflow.exceptions import (
    UpstreamReadFailed,
    UpstreamReadNotStarted,
    UpstreamReadUnanswered,
    UpstreamReviewsUnavailable,
)
from github_workflow.locations import NotesFile
from github_workflow.notes.branch import NotesBranch
from github_workflow.workflow_templates import (
    ActionRequirement,
    NotesBranchWorkflow,
    UpstreamReviewPlaceholder,
)

# %% requests


class UpstreamReviewKey(StrEnum):
    """
    The keys of a request, and of its answer, as the notes branch holds them.
    """

    UPSTREAM = "upstream"
    """
    The repository the fork was forked from, as ``owner/name``.
    """

    FORK_OWNER = "fork_owner"
    """
    The owner of the fork.
    """

    BRANCH = "branch"
    """
    The fork's branch.
    """

    ANSWERS = "answers"
    """
    GitHub's answers to the reads, in an answer.
    """


@dataclass(frozen=True)
class UpstreamReviewRequest:
    """
    A request for the reviews of the pull request a fork's branch has open upstream.
    """

    upstream: Repository
    """
    The repository the fork was forked from.
    """

    fork_owner: str
    """
    The owner of the fork, whose branch the pull request is opened from.
    """

    branch: str
    """
    The fork's branch.
    """

    name: str = field(default_factory=NotesBranch.queued_file_name)
    """
    The request's file name on the notes branch, its answer's too.
    """

    def to_json(self) -> str:
        """:return: The request, as the notes branch holds it."""
        return json.dumps(
            {
                UpstreamReviewKey.UPSTREAM: self.upstream.full_name,
                UpstreamReviewKey.FORK_OWNER: self.fork_owner,
                UpstreamReviewKey.BRANCH: self.branch,
            },
            indent=2,
        )

    @classmethod
    def from_file(cls, path: Path) -> UpstreamReviewRequest:
        """
        :param path: A request, as :meth:`to_json` wrote it.
        :return: The request.
        """
        data = json.loads(path.read_text())
        return cls(
            Repository.parse(data[UpstreamReviewKey.UPSTREAM]),
            data[UpstreamReviewKey.FORK_OWNER],
            data[UpstreamReviewKey.BRANCH],
            path.name,
        )

    def snapshot(self, client: GraphQLClient) -> UpstreamPullRequestSnapshot:
        """
        :param client: How the reads reach GitHub, or the answers they got before.
        :return: The upstream pull request's reviews, threads and checks.
        :raises UpstreamPullRequestNotFound: If the branch has none upstream.
        """
        reader = UpstreamPullRequestReader(client, self.upstream, self.fork_owner)
        return reader.read_current_state(
            reader.resolve_pull_request_number(self.branch)
        )


# %% reading them


class UpstreamReviews(ABC):
    """
    Reads the pull request a fork's branch has open upstream.
    """

    @abstractmethod
    def snapshot(
        self, request: UpstreamReviewRequest
    ) -> UpstreamPullRequestSnapshot | UpstreamReviewsUnavailable:
        """
        :param request: Which pull request.
        :return: Its reviews, threads and checks, or why they could not be read.
        """


@dataclass(frozen=True)
class DirectUpstreamReviews(UpstreamReviews):
    """
    Reads it through GitHub's GraphQL API, which the person's own login reaches.
    """

    client: GraphQLClient
    """
    How the reads reach GitHub.
    """

    def snapshot(
        self, request: UpstreamReviewRequest
    ) -> UpstreamPullRequestSnapshot | UpstreamReviewsUnavailable:
        return request.snapshot(self.client)


@dataclass(frozen=True)
class ForwardedUpstreamReviews(UpstreamReviews):
    """
    Has the fork's Actions read it: queues the request on the notes branch with the
    workflow answering it, then waits for the answer there and reads it again from
    GitHub's recorded answers, giving up early when the fork's Actions start no run for
    it, after asking again, or the run fails.
    """

    notes: NotesBranch
    """
    The fork's notes branch.
    """

    fork: Repository
    """
    The fork, whose Actions answer the request.
    """

    workflows: RepositoryWorkflows
    """
    Reads the fork's workflow runs.
    """

    timeout_seconds: float = 300.0
    """
    How long to wait for the answer.
    """

    start_seconds: float = 90.0
    """
    How long the fork's Actions may take to start the run answering the request.
    """

    interval_seconds: float = 5.0
    """
    How long to wait between looks.
    """

    tries: int = 2
    """
    How many times the request is made before the fork's Actions are taken to be off.
    """

    def snapshot(
        self, request: UpstreamReviewRequest
    ) -> UpstreamPullRequestSnapshot | UpstreamReviewsUnavailable:
        """
        Asks again, under a new name, when no run starts for a request within
        :attr:`start_seconds`, up to :attr:`tries` times.
        """
        for _ in range(self.tries):
            answered = self.answer(request)
            if not isinstance(answered, UpstreamReadNotStarted):
                return answered
            request = replace(request, name=NotesBranch.queued_file_name())
        return answered

    def answer(
        self, request: UpstreamReviewRequest
    ) -> UpstreamPullRequestSnapshot | UpstreamReviewsUnavailable:
        """
        :param request: The request to queue and wait for.
        :return: The upstream pull request, read again from the answer, or why no
            answer came.
        """
        queued = self.queue(request)
        answer = NotesFile.UPSTREAM_REVIEW_ANSWERS / request.name
        waited = 0.0
        while True:
            self.notes.fetch()
            saved = self.notes.read(answer)
            if saved is not None:
                answers = json.loads(saved)[UpstreamReviewKey.ANSWERS]
                return request.snapshot(ReplayingGraphQLClient(answers))
            stopped = self.stopped_run(queued, waited)
            if stopped is not None:
                return stopped
            if waited >= self.timeout_seconds:
                return UpstreamReadUnanswered(request.upstream, self.timeout_seconds)
            time.sleep(self.interval_seconds)
            waited += self.interval_seconds

    def stopped_run(
        self, queued: str, waited: float
    ) -> UpstreamReviewsUnavailable | None:
        """
        :param queued: The notes branch's commit queuing the request.
        :param waited: How long the answer was waited for so far.
        :return: That no run answering the request started within
            :attr:`start_seconds`, or that it failed; ``None`` while one may still
            answer.
        """
        runs = [
            run
            for run in self.workflows.runs_on(self.notes.branch.name)
            if run.commit == queued
            and run.path == str(NotesFile.UPSTREAM_REVIEW_WORKFLOW)
        ]
        if not runs:
            started_late = waited >= self.start_seconds
            return (
                UpstreamReadNotStarted(self.fork, self.start_seconds)
                if started_late
                else None
            )
        conclusion = runs[0].conclusion
        if conclusion in (None, WorkflowRunConclusion.SUCCESS):
            return None
        return UpstreamReadFailed(runs[0].url, conclusion)

    def queue(self, request: UpstreamReviewRequest) -> str:
        """
        :param request: The request to write, with the workflow answering it.
        :return: The notes branch's commit queuing it.
        """
        workflow = NotesBranchWorkflow.UPSTREAM_REVIEWS.files(
            self.notes.branch.name,
            {
                UpstreamReviewPlaceholder.REQUESTS_DIRECTORY: str(
                    NotesFile.UPSTREAM_REVIEW_REQUESTS
                ),
                UpstreamReviewPlaceholder.ANSWERS_DIRECTORY: str(
                    NotesFile.UPSTREAM_REVIEW_ANSWERS
                ),
                **ActionRequirement.placeholder_values(__name__),
            },
        )
        self.notes.fetch()
        self.notes.write(
            {
                NotesFile.UPSTREAM_REVIEW_REQUESTS / request.name: request.to_json(),
                **workflow,
            },
            f"Ask for the upstream reviews of {request.branch}",
        )
        self.notes.fetch()
        return self.notes.branch.tracking_branch.commit().hash


# %% answering them, on the runner


@dataclass(frozen=True)
class UpstreamReviewAnswering:
    """
    Answers every waiting request: reads its pull request upstream, saves GitHub's
    answers under the request's name, and removes the request.
    """

    requests: Path
    """
    The directory holding the requests.
    """

    answers: Path
    """
    The directory the answers are saved in; answers of earlier runs are removed.
    """

    client: GraphQLClient
    """
    How the reads reach GitHub.
    """

    def run(self) -> list[str]:
        """
        :return: The name of every request answered.
        :raises UpstreamPullRequestNotFound: If a request's branch has no pull request
            upstream.
        """
        for earlier in self.answers.glob("*.json"):
            earlier.unlink()
        self.answers.mkdir(parents=True, exist_ok=True)
        answered = []
        for path in sorted(self.requests.glob("*.json")):
            request = UpstreamReviewRequest.from_file(path)
            recording = RecordingGraphQLClient(self.client)
            request.snapshot(recording)
            saved: dict[str, Any] = {UpstreamReviewKey.ANSWERS: recording.answers}
            (self.answers / request.name).write_text(json.dumps(saved))
            path.unlink()
            answered.append(request.name)
        return answered


def main() -> None:
    """
    Answer the requests waiting in the directory the command line names.
    """
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("requests", type=Path, help="the directory of the requests")
    parser.add_argument("answers", type=Path, help="the directory of the answers")
    arguments = parser.parse_args()
    answered = UpstreamReviewAnswering(
        arguments.requests, arguments.answers, GitHubApi.from_environment()
    ).run()
    print(f"answered {', '.join(answered) or 'nothing'}")


if __name__ == "__main__":
    main()
