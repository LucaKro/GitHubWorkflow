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
from dataclasses import dataclass, replace
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


# %% why they could not be read


class UpstreamReviewsUnavailable(ABC):
    """
    Why the pull request opened upstream could not be read.
    """

    @abstractmethod
    def reason(self) -> str:
        """:return: What kept it from being read."""

    @abstractmethod
    def correction(self) -> str:
        """:return: What to do about it."""

    def line(self) -> str:
        """:return: Both, in one line."""
        return f"upstream reviews not read: {self.reason()}. {self.correction()}"


@dataclass(frozen=True)
class UpstreamReadNotStarted(UpstreamReviewsUnavailable):
    """
    The fork's Actions started no run answering the request: Actions are off on the
    fork, or its workflows are, or GitHub dropped the push.
    """

    fork: Repository
    """
    The fork.
    """

    start_seconds: float
    """
    How long each request's run was waited for.
    """

    def reason(self) -> str:
        return (
            f"{self.fork}'s Actions started no run reading them within "
            f"{self.start_seconds:.0f} seconds of each request"
        )

    def correction(self) -> str:
        return (
            f"Ask the person to check that Actions and the fork's workflows are on at "
            f"{self.fork.url}/actions, then list the reviews again"
        )


@dataclass(frozen=True)
class UpstreamReadFailed(UpstreamReviewsUnavailable):
    """
    The fork's Actions run answering the request failed.
    """

    run: str
    """
    The run's page, with its log.
    """

    conclusion: WorkflowRunConclusion
    """
    How it ended.
    """

    def reason(self) -> str:
        return f"the run reading them ended in {self.conclusion}: {self.run}"

    def correction(self) -> str:
        return "Read its log, and file what went wrong as a finding of the workflow"


@dataclass(frozen=True)
class UpstreamReadUnanswered(UpstreamReviewsUnavailable):
    """
    The fork's Actions did not answer the request in time.
    """

    upstream: Repository
    """
    The repository the pull request is open on.
    """

    timeout_seconds: float
    """
    How long the answer was waited for.
    """

    def reason(self) -> str:
        return (
            f"the fork's Actions did not read them on {self.upstream} within "
            f"{self.timeout_seconds:.0f} seconds"
        )

    def correction(self) -> str:
        return "List the reviews again; the run reading them may still be going"


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
            request = replace(request, name=f"{time.time_ns()}.json")
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
        answer = NotesFile.UPSTREAM_REVIEW_ANSWERS.value / request.name
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
            and run.path == str(NotesFile.UPSTREAM_REVIEW_WORKFLOW.value)
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
