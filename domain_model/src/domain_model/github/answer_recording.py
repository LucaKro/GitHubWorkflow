"""
GitHub's answers to one run of reads, kept by what was asked, so the same reads made
elsewhere and in any order see what GitHub answered then.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from domain_model.code_version import CodeVersion
from domain_model.github.clients import GitHubReader
from domain_model.github.exceptions import (
    RecordedReadMissingError,
    UnreadableRecordingError,
)

# %% one read


class ReadTransport(StrEnum):
    """
    How a read reached GitHub.
    """

    REST = "rest"
    """
    One REST response.
    """

    REST_PAGES = "rest pages"
    """
    Every page of a paged REST response.
    """

    GRAPHQL = "graphql"
    """
    One GraphQL query.
    """


@dataclass(frozen=True)
class GitHubRead:
    """
    One read asked of GitHub: a REST path, or a GraphQL document and its variables.
    """

    transport: ReadTransport
    """
    How it reaches GitHub.
    """

    address: str
    """
    The REST path, query included, or the GraphQL document.
    """

    variables: Mapping[str, Any] = field(default_factory=dict)
    """
    The GraphQL document's variables, empty for a REST read.
    """

    @property
    def key(self) -> str:
        """:return: What tells this read apart from every other, as text."""
        return json.dumps(
            [self.transport, self.address, dict(self.variables)], sort_keys=True
        )

    @property
    def described(self) -> str:
        """:return: The read, as a message names it: a document by its first line."""
        first_line = self.address.strip().splitlines()[0] if self.address else ""
        variables = (
            f" with {json.dumps(dict(self.variables))}" if self.variables else ""
        )
        return f"{self.transport} {first_line}{variables}"


# %% the recording


class AnswerRecordingKey(StrEnum):
    """
    The keys of an :class:`AnswerRecording` as JSON.
    """

    RECORDER = "recorder"
    """
    The code that made the recording.
    """

    ANSWERS = "answers"
    """
    Every read and its answer.
    """

    TRANSPORT = "transport"
    """
    How a read reached GitHub.
    """

    ADDRESS = "address"
    """
    A read's REST path or GraphQL document.
    """

    VARIABLES = "variables"
    """
    A GraphQL read's variables.
    """

    ANSWER = "answer"
    """
    What GitHub answered a read.
    """


@dataclass(frozen=True)
class AnsweredRead:
    """
    One read, and what GitHub answered it.
    """

    read: GitHubRead
    """
    The read.
    """

    answer: Any
    """
    The parsed answer: a REST response, its pages, or a GraphQL query's ``data``.
    """


@dataclass(frozen=True)
class AnswerRecording:
    """
    GitHub's answers to one run of reads, by what was asked, and the code that recorded
    them.
    """

    recorder: CodeVersion
    """
    The code that made the recording.
    """

    answers: dict[str, AnsweredRead] = field(default_factory=dict)
    """
    Each read's answer, by the read's :attr:`GitHubRead.key`.
    """

    @classmethod
    def started(cls) -> AnswerRecording:
        """:return: An empty recording, made by the code running now."""
        return cls(CodeVersion.running())

    def keep(self, read: GitHubRead, answer: Any) -> Any:
        """
        :param read: A read just made.
        :param answer: What GitHub answered it.
        :return: The answer.
        """
        self.answers[read.key] = AnsweredRead(read, answer)
        return answer

    def to_json(self) -> str:
        """:return: The recording, as :meth:`from_json` reads it."""
        return json.dumps(
            {
                AnswerRecordingKey.RECORDER: self.recorder.to_json(),
                AnswerRecordingKey.ANSWERS: [
                    {
                        AnswerRecordingKey.TRANSPORT: recorded.read.transport,
                        AnswerRecordingKey.ADDRESS: recorded.read.address,
                        AnswerRecordingKey.VARIABLES: dict(recorded.read.variables),
                        AnswerRecordingKey.ANSWER: recorded.answer,
                    }
                    for recorded in self.answers.values()
                ],
            }
        )

    @classmethod
    def from_json(cls, text: str) -> AnswerRecording:
        """
        :param text: A recording, as :meth:`to_json` writes it.
        :return: The recording.
        :raises UnreadableRecordingError: If it is not in that form.
        """
        data = json.loads(text)
        for key in (AnswerRecordingKey.RECORDER, AnswerRecordingKey.ANSWERS):
            if key not in data:
                raise UnreadableRecordingError(key)
        recording = cls(CodeVersion.from_json(data[AnswerRecordingKey.RECORDER]))
        for entry in data[AnswerRecordingKey.ANSWERS]:
            read = GitHubRead(
                ReadTransport(entry[AnswerRecordingKey.TRANSPORT]),
                entry[AnswerRecordingKey.ADDRESS],
                entry[AnswerRecordingKey.VARIABLES],
            )
            recording.keep(read, entry[AnswerRecordingKey.ANSWER])
        return recording


# %% recording and replaying


@dataclass(frozen=True)
class RecordingClient(GitHubReader):
    """
    Sends each read through another client, keeping every answer for a
    :class:`ReplayingClient` to give again elsewhere.
    """

    client: GitHubReader
    """
    The client the reads go through.
    """

    recording: AnswerRecording = field(default_factory=AnswerRecording.started)
    """
    Every answer so far.
    """

    def get(self, path: str) -> Any:
        read = GitHubRead(ReadTransport.REST, path)
        return self.recording.keep(read, self.client.get(path))

    def get_pages(self, path: str) -> list[Any]:
        read = GitHubRead(ReadTransport.REST_PAGES, path)
        return self.recording.keep(read, self.client.get_pages(path))

    def execute(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        read = GitHubRead(ReadTransport.GRAPHQL, query, variables)
        return self.recording.keep(read, self.client.execute(query, variables))


@dataclass(frozen=True)
class ReplayingClient(GitHubReader):
    """
    Answers each read with the answer a :class:`RecordingClient` kept for the same
    read.
    """

    recording: AnswerRecording
    """
    The recorded answers.
    """

    def get(self, path: str) -> Any:
        """
        :meth:`RestClient.get`, answered from the recording.

        :raises RecordedReadMissingError: If the recording holds no answer to it.
        """
        return self.recorded(GitHubRead(ReadTransport.REST, path))

    def get_pages(self, path: str) -> list[Any]:
        """
        :meth:`RestClient.get_pages`, answered from the recording.

        :raises RecordedReadMissingError: If the recording holds no answer to it.
        """
        return self.recorded(GitHubRead(ReadTransport.REST_PAGES, path))

    def execute(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        """
        :meth:`GraphQLClient.execute`, answered from the recording.

        :raises RecordedReadMissingError: If the recording holds no answer to it.
        """
        return self.recorded(GitHubRead(ReadTransport.GRAPHQL, query, variables))

    def recorded(self, read: GitHubRead) -> Any:
        """
        :param read: A read.
        :return: The answer recorded for it.
        :raises RecordedReadMissingError: If the recording holds none.
        """
        recorded = self.recording.answers.get(read.key)
        if recorded is None:
            raise RecordedReadMissingError(
                read.described, self.recording.recorder, CodeVersion.running()
            )
        return recorded.answer
