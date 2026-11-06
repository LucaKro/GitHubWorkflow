"""
The reviews of a fork's pull request opened upstream, read where the upstream can be
reached: directly, with the person's own GitHub login, or, from a cloud session whose
proxy refuses the upstream, by the fork's Actions, which read them for a request queued
on the notes branch and save GitHub's answers there for the session to read them from.

Nothing is ever written upstream.

Usage on the runner: ``python -m github_workflow.upstream_reviews <requests directory>
<answers directory>``; answers every waiting request and removes it.
"""

from __future__ import annotations

import argparse
import json
import shlex
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from basstler_domain_model.github.clients import (
    GitHubApi,
    GraphQLClient,
    RecordingGraphQLClient,
    ReplayingGraphQLClient,
)
from basstler_domain_model.github.pull_request_models import (
    UpstreamPullRequestSnapshot,
)
from basstler_domain_model.github.readers import UpstreamPullRequestReader
from basstler_domain_model.github.repository_client import RepositoryWorkflows
from basstler_domain_model.github.vocabulary import WorkflowRunConclusion
from basstler_domain_model.repository import Repository

from github_workflow.exceptions import (
    UpstreamReviewsFailedError,
    UpstreamReviewsNotStartedError,
    UpstreamReviewsUnansweredError,
)
from github_workflow.label_events import ActionRequirement
from github_workflow.locations import NotesFile, WorkflowTemplate
from github_workflow.notes.branch import NotesBranch

# %% requests


class UpstreamReviewKey(StrEnum):
    """
    The keys of a request, and of its answer, as the notes branch holds them.
    """

    UPSTREAM = "upstream"
    FORK_OWNER = "fork_owner"
    BRANCH = "branch"
    ANSWERS = "answers"


class UpstreamReviewPlaceholder(StrEnum):
    """
    The names the reading workflow template leaves to be filled in.
    """

    NOTES_BRANCH = "__NOTES_BRANCH__"
    """
    The notes branch, whose pushes run the workflow.
    """

    REQUESTS_DIRECTORY = "__REQUESTS_DIRECTORY__"
    """
    The directory holding the requests.
    """

    ANSWERS_DIRECTORY = "__ANSWERS_DIRECTORY__"
    """
    The directory the answers are saved in.
    """

    REQUIREMENTS = "__REQUIREMENTS__"
    """
    What ``pip`` installs.
    """

    ENTRY_POINT = "__ENTRY_POINT__"
    """
    The command answering the requests, before the two directories.
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

    name: str
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
    def snapshot(self, request: UpstreamReviewRequest) -> UpstreamPullRequestSnapshot:
        """
        :param request: Which pull request.
        :return: Its reviews, threads and checks.
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

    def snapshot(self, request: UpstreamReviewRequest) -> UpstreamPullRequestSnapshot:
        return request.snapshot(self.client)


@dataclass(frozen=True)
class ForwardedUpstreamReviews(UpstreamReviews):
    """
    Has the fork's Actions read it: queues the request on the notes branch with the
    workflow answering it, then waits for the answer there and reads it again from
    GitHub's recorded answers, giving up early when the fork's Actions start no run for
    it or the run fails.
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

    def snapshot(self, request: UpstreamReviewRequest) -> UpstreamPullRequestSnapshot:
        """
        :raises UpstreamReviewsNotStartedError: If the fork's Actions started no run
            for the request in time.
        :raises UpstreamReviewsFailedError: If the run answering it failed.
        :raises UpstreamReviewsUnansweredError: If no answer came in time.
        """
        queued = self.queue(request)
        answer = NotesFile.UPSTREAM_REVIEW_ANSWERS.value / request.name
        waited = 0.0
        while True:
            self.notes.fetch()
            saved = self.notes.read(answer)
            if saved is not None:
                answers = json.loads(saved)[UpstreamReviewKey.ANSWERS]
                return request.snapshot(ReplayingGraphQLClient(answers))
            self.check_run(queued, waited)
            if waited >= self.timeout_seconds:
                raise UpstreamReviewsUnansweredError(
                    request.upstream, self.timeout_seconds
                )
            time.sleep(self.interval_seconds)
            waited += self.interval_seconds

    def check_run(self, queued: str, waited: float) -> None:
        """
        :param queued: The notes branch's commit queuing the request.
        :param waited: How long the answer was waited for so far.
        :raises UpstreamReviewsNotStartedError: If no run answering the request started
            within :attr:`start_seconds`.
        :raises UpstreamReviewsFailedError: If the run answering it failed.
        """
        runs = [
            run
            for run in self.workflows.runs_on(self.notes.branch.name)
            if run.commit == queued
            and run.path == str(NotesFile.UPSTREAM_REVIEW_WORKFLOW.value)
        ]
        if not runs:
            if waited >= self.start_seconds:
                raise UpstreamReviewsNotStartedError(self.fork, self.start_seconds)
            return
        conclusion = runs[0].conclusion
        if conclusion not in (None, WorkflowRunConclusion.SUCCESS):
            raise UpstreamReviewsFailedError(runs[0].url, conclusion)

    def queue(self, request: UpstreamReviewRequest) -> str:
        """
        :param request: The request to write, with the workflow answering it.
        :return: The notes branch's commit queuing it.
        """
        workflow = WorkflowTemplate.UPSTREAM_REVIEW_WORKFLOW.value.read_text()
        for placeholder, value in {
            UpstreamReviewPlaceholder.NOTES_BRANCH: self.notes.branch.name,
            UpstreamReviewPlaceholder.REQUESTS_DIRECTORY: str(
                NotesFile.UPSTREAM_REVIEW_REQUESTS.value
            ),
            UpstreamReviewPlaceholder.ANSWERS_DIRECTORY: str(
                NotesFile.UPSTREAM_REVIEW_ANSWERS.value
            ),
            UpstreamReviewPlaceholder.REQUIREMENTS: shlex.join(list(ActionRequirement)),
            UpstreamReviewPlaceholder.ENTRY_POINT: f"python -m {__name__}",
        }.items():
            workflow = workflow.replace(placeholder, value)
        self.notes.fetch()
        self.notes.write(
            {
                NotesFile.UPSTREAM_REVIEW_REQUESTS.value
                / request.name: (request.to_json()),
                NotesFile.UPSTREAM_REVIEW_WORKFLOW.value: workflow,
            },
            f"Ask for the upstream reviews of {request.branch}",
        )
        self.notes.fetch()
        return self.notes.git.commit_at(self.notes.branch.tracking_reference)


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
