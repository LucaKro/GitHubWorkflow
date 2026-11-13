"""
Reads a cloud session cannot make itself, made for it by the Actions of the owner's
repository: a request queued on the notes branch is answered there with GitHub's
answers to the reads, which the session replays to read the same again.
"""

from __future__ import annotations

import argparse
import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Any, Generic, Self, TypeVar

from domain_model.class_property import classproperty
from domain_model.code_version import CodeVersion
from domain_model.git.revisions import TextFiles
from domain_model.github.answer_recording import (
    AnswerRecording,
    RecordingClient,
    ReplayingClient,
)
from domain_model.github.clients import GitHubApi, GitHubReader
from domain_model.github.exceptions import (
    RecordedReadMissingError,
    UnreadableRecordingError,
)
from domain_model.github.repository_client import RepositoryWorkflows
from domain_model.github.vocabulary import WorkflowRunConclusion
from domain_model.repository import Repository

from github_workflow.exceptions import (
    ForwardedAnswerMissing,
    ForwardedAnswerUnreadable,
    ForwardedReadFailed,
    ForwardedReadNotStarted,
    ForwardedReadUnanswered,
    ForwardedReadUnavailable,
)
from github_workflow.notes.branch import NotesBranch
from github_workflow.workflow_templates import ForwardedSubject

# %% a request

ReadResult = TypeVar("ReadResult")
"""
What a request's reads give.
"""


@dataclass(frozen=True)
class ForwardedRequest(Generic[ReadResult], ABC):
    """
    Reads to be made for a session, which give the same wherever they are made, once
    GitHub's answers to them are recorded.
    """

    name: str = field(default_factory=NotesBranch.queued_file_name, kw_only=True)
    """
    The request's file name on the notes branch, its answer's too.
    """

    @classproperty
    @abstractmethod
    def subject(cls) -> ForwardedSubject:
        """
        What the request asks to be read.
        """

    @abstractmethod
    def to_json(self) -> dict[str, Any]:
        """:return: The request, as the notes branch holds it."""

    @classmethod
    @abstractmethod
    def from_json(cls, data: dict[str, Any], name: str) -> Self:
        """
        :param data: A request, as :meth:`to_json` wrote it.
        :param name: Its file name on the notes branch.
        :return: The request.
        """

    @abstractmethod
    def read(self, client: GitHubReader) -> ReadResult:
        """
        :param client: How the reads reach GitHub, or the answers they got before.
        :return: What the reads give.
        """


# %% its answer


class ForwardedAnswerKey(StrEnum):
    """
    The keys of an answer, as the notes branch holds it.
    """

    REQUEST = "request"
    """
    The request answered.
    """

    RECORDING = "recording"
    """
    GitHub's answers to its reads.
    """


@dataclass(frozen=True)
class ForwardedAnswer(Generic[ReadResult]):
    """
    A request, and GitHub's answers to its reads.
    """

    request: ForwardedRequest[ReadResult]
    """
    The request answered.
    """

    recording: AnswerRecording
    """
    GitHub's answers to its reads.
    """

    @classmethod
    def from_request(
        cls, request: ForwardedRequest[ReadResult], client: GitHubReader
    ) -> ForwardedAnswer[ReadResult]:
        """
        :param request: A request.
        :param client: How its reads reach GitHub.
        :return: The request, answered.
        """
        recording = RecordingClient(client)
        request.read(recording)
        return cls(request, recording.recording)

    def to_json(self) -> str:
        """:return: The answer, as the notes branch holds it."""
        return json.dumps(
            {
                ForwardedAnswerKey.REQUEST: self.request.to_json(),
                ForwardedAnswerKey.RECORDING: json.loads(self.recording.to_json()),
            }
        )

    @staticmethod
    def replay(
        saved: str,
        request_type: type[ForwardedRequest[ReadResult]],
        name: str,
    ) -> ReadResult | ForwardedReadUnavailable:
        """
        :param saved: An answer, as :meth:`to_json` wrote it.
        :param request_type: The kind of request it answers.
        :param name: The answer's file name on the notes branch.
        :return: What the request's reads give, read again from GitHub's answers, or
            why this session's code cannot read them.
        """
        data = json.loads(saved)
        subject = request_type.subject
        if set(data) != set(ForwardedAnswerKey):
            return ForwardedAnswerUnreadable(
                subject,
                "the answer is not in the form this session reads",
                None,
                CodeVersion.from_installation(),
            )
        request = request_type.from_json(data[ForwardedAnswerKey.REQUEST], name)
        try:
            recording = AnswerRecording.from_json(
                json.dumps(data[ForwardedAnswerKey.RECORDING])
            )
            return request.read(ReplayingClient(recording))
        except RecordedReadMissingError as missing:
            return ForwardedAnswerUnreadable(
                subject, missing.error_message(), missing.recorder, missing.replayer
            )
        except UnreadableRecordingError as unreadable:
            return ForwardedAnswerUnreadable(
                subject,
                unreadable.error_message(),
                None,
                CodeVersion.from_installation(),
            )


# %% having them read


@dataclass(frozen=True)
class ForwardedReading:
    """
    Has the owner's repository's Actions make a request's reads: queues the request on
    the notes branch with the workflow answering it, then waits for the answer there,
    giving up early when the Actions start no run for it, after asking again, or the
    run fails.
    """

    notes: NotesBranch
    """
    The repository's notes branch.
    """

    repository: Repository
    """
    The repository, whose Actions answer the request.
    """

    workflows: RepositoryWorkflows
    """
    Reads the repository's workflow runs.
    """

    timeout_seconds: float = 300.0
    """
    How long to wait for the answer.
    """

    start_seconds: float = 90.0
    """
    How long the repository's Actions may take to start the run answering the request.
    """

    interval_seconds: float = 5.0
    """
    How long to wait between looks.
    """

    tries: int = 2
    """
    How many times the request is made before the repository's Actions are taken to be
    off.
    """

    def read(
        self, request: ForwardedRequest[ReadResult]
    ) -> ReadResult | ForwardedReadUnavailable:
        """
        :param request: The request to have answered.
        :return: What its reads give, or why they could not be had; asks again, under
            a new name, when no run starts for a request within :attr:`start_seconds`,
            up to :attr:`tries` times.
        """
        for _ in range(self.tries):
            answered = self.answer(request)
            if not isinstance(answered, ForwardedReadNotStarted):
                return answered
            request = replace(request, name=NotesBranch.queued_file_name())
        return answered

    def answer(
        self, request: ForwardedRequest[ReadResult]
    ) -> ReadResult | ForwardedReadUnavailable:
        """
        :param request: The request to queue and wait for.
        :return: What its reads give, read again from the answer, or why no answer
            came.
        """
        queued = self.queue(request)
        answer = request.subject.answers / request.name
        waited = 0.0
        while True:
            self.notes.fetch()
            saved = self.notes.read(answer)
            if saved is not None:
                return ForwardedAnswer.replay(saved, type(request), request.name)
            stopped = self.stopped_run(request.subject, queued, waited)
            if stopped is not None:
                return stopped
            if waited >= self.timeout_seconds:
                return ForwardedReadUnanswered(
                    request.subject, self.repository, self.timeout_seconds
                )
            time.sleep(self.interval_seconds)
            waited += self.interval_seconds

    def latest_answer(
        self, request_type: type[ForwardedRequest[ReadResult]]
    ) -> ReadResult | ForwardedReadUnavailable:
        """
        :param request_type: A kind of request.
        :return: What the newest answer saved on the notes branch gives, as last
            fetched, or why there is none to read.
        """
        subject = request_type.subject
        names = self.notes.branch.tracking_branch.file_names(subject.answers)
        if not names:
            return ForwardedAnswerMissing(subject, self.repository)
        newest = max(names)
        saved = self.notes.read(subject.answers / newest) or ""
        return ForwardedAnswer.replay(saved, request_type, newest)

    def stopped_run(
        self, subject: ForwardedSubject, queued: str, waited: float
    ) -> ForwardedReadUnavailable | None:
        """
        :param subject: What the request asks to be read.
        :param queued: The notes branch's commit queuing the request.
        :param waited: How long the answer was waited for so far.
        :return: That no run answering the request started within
            :attr:`start_seconds`, or that it failed; ``None`` while one may still
            answer.
        """
        runs = [
            run
            for run in self.workflows.branch_runs(self.notes.branch.name)
            if run.commit == queued
            and run.path == str(subject.workflow.destination.value)
        ]
        if not runs:
            started_late = waited >= self.start_seconds
            return (
                ForwardedReadNotStarted(subject, self.repository, self.start_seconds)
                if started_late
                else None
            )
        conclusion = runs[0].conclusion
        if conclusion in (None, WorkflowRunConclusion.SUCCESS):
            return None
        return ForwardedReadFailed(subject, runs[0].url, conclusion)

    def queue(self, request: ForwardedRequest[Any]) -> str:
        """
        :param request: The request to write, with the workflow answering it.
        :return: The notes branch's commit queuing it.
        """
        subject = request.subject
        workflow = subject.workflow_files(
            self.notes.branch.name, type(request).__module__
        )
        request_file = TextFiles(
            {subject.requests / request.name: json.dumps(request.to_json(), indent=2)}
        )
        self.notes.fetch()
        self.notes.write(
            request_file.combine(workflow), f"Ask for the {subject.described}"
        )
        self.notes.fetch()
        return self.notes.branch.tracking_branch.commit().hash


# %% answering them, on the runner


@dataclass(frozen=True)
class ForwardedReadAnswering(Generic[ReadResult]):
    """
    Answers every waiting request of one kind: makes its reads, saves the request with
    GitHub's answers under the request's name, and removes the request.
    """

    request_type: type[ForwardedRequest[ReadResult]]
    """
    The kind of request answered.
    """

    requests: Path
    """
    The directory holding the requests.
    """

    answers: Path
    """
    The directory the answers are saved in; answers of earlier runs are removed.
    """

    client: GitHubReader
    """
    How the reads reach GitHub.
    """

    def run(self) -> list[str]:
        """
        :return: The name of every request answered.
        """
        for earlier in self.answers.glob("*.json"):
            earlier.unlink()
        self.answers.mkdir(parents=True, exist_ok=True)
        answered = []
        for path in sorted(self.requests.glob("*.json")):
            request = self.request_type.from_json(
                json.loads(path.read_text()), path.name
            )
            answer = ForwardedAnswer.from_request(request, self.client)
            (self.answers / request.name).write_text(answer.to_json())
            path.unlink()
            answered.append(request.name)
        return answered

    @classmethod
    def answer_command_line(cls, request_type: type[ForwardedRequest[Any]]) -> None:
        """
        Answer the requests waiting in the directory the command line names, printing
        which were answered.

        :param request_type: The kind of request answered.
        """
        parser = argparse.ArgumentParser(
            description=f"Answer the requests for {request_type.subject.described}."
        )
        parser.add_argument("requests", type=Path, help="the directory of the requests")
        parser.add_argument("answers", type=Path, help="the directory of the answers")
        arguments = parser.parse_args()
        answered = cls(
            request_type,
            arguments.requests,
            arguments.answers,
            GitHubApi.from_environment(),
        ).run()
        print(f"answered {', '.join(answered) or 'nothing'}")
