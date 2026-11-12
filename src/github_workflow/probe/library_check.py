"""
One call through :mod:`domain_model`, run as a process of its own; a refusal
ends only this check, with the library's own error as its message.

Usage: ``python -m github_workflow.probe.library_check <check> <owner/name>
[<argument>]``
"""

from __future__ import annotations

import json
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum

from domain_model.class_family import ClassFamily
from domain_model.class_property import classproperty
from domain_model.github.clients import GitHubApi
from domain_model.github.pull_request_models import UpstreamPullRequestSnapshot
from domain_model.github.readers import ReadSource
from domain_model.github.repository_client import GitHubRepository
from domain_model.repository import Repository

# %% the checks


class LibraryCheck(StrEnum):
    """
    The calls through the library a probe makes, by the name the command line takes.
    """

    AUTHENTICATED_LOGIN = "authenticated-login"
    """
    Whose credential the REST client calls with.
    """

    LABELS = "labels"
    """
    The labels the repository carries.
    """

    OPEN_PULL_REQUESTS = "open-pull-requests"
    """
    The repository's open pull requests.
    """

    CHECK_STATE = "check-state"
    """
    The verdict over the checks on a commit, given as the argument.
    """

    PULL_REQUEST_REVIEW_STATE = "pull-request-review-state"
    """
    A pull request's review threads and checks, read the way this session's place
    reaches them, given its number as the argument.
    """


# %% the calls


@dataclass(frozen=True)
class LibraryCall(ClassFamily, ABC):
    """
    One check's call through the library.
    """

    @classproperty
    @abstractmethod
    def check(cls) -> LibraryCheck:
        """
        The check the call makes.
        """

    @abstractmethod
    def read(self, repository: Repository, argument: str) -> str:
        """
        :param repository: The repository the session works in.
        :param argument: The commit or pull request number the check needs, if any.
        :return: What it read, in one line.
        """

    @classmethod
    def from_check(cls, check: LibraryCheck) -> LibraryCall:
        """
        :param check: A check.
        :return: The call it makes.
        """
        return next(call() for call in cls.concrete_subclasses() if call.check is check)


@dataclass(frozen=True)
class AuthenticatedLoginCall(LibraryCall):
    """
    Reads whose credential the REST client calls with.
    """

    @classproperty
    def check(cls) -> LibraryCheck:
        return LibraryCheck.AUTHENTICATED_LOGIN

    def read(self, repository: Repository, argument: str) -> str:
        return GitHubRepository.from_environment(repository).authenticated_login()


@dataclass(frozen=True)
class LabelsCall(LibraryCall):
    """
    Reads the labels the repository carries.
    """

    @classproperty
    def check(cls) -> LibraryCheck:
        return LibraryCheck.LABELS

    def read(self, repository: Repository, argument: str) -> str:
        return ", ".join(sorted(GitHubRepository.from_environment(repository).labels()))


@dataclass(frozen=True)
class OpenPullRequestsCall(LibraryCall):
    """
    Counts the repository's open pull requests.
    """

    @classproperty
    def check(cls) -> LibraryCheck:
        return LibraryCheck.OPEN_PULL_REQUESTS

    def read(self, repository: Repository, argument: str) -> str:
        client = GitHubRepository.from_environment(repository)
        return f"{len(client.open_pull_requests())} open"


@dataclass(frozen=True)
class CheckStateCall(LibraryCall):
    """
    Reads the verdict over the checks on a commit.
    """

    @classproperty
    def check(cls) -> LibraryCheck:
        return LibraryCheck.CHECK_STATE

    def read(self, repository: Repository, argument: str) -> str:
        return str(GitHubRepository.from_environment(repository).check_state(argument))


@dataclass(frozen=True)
class PullRequestReviewStateCall(LibraryCall):
    """
    Reads a pull request's review threads and checks the way this session's place
    reaches them.
    """

    @classproperty
    def check(cls) -> LibraryCheck:
        return LibraryCheck.PULL_REQUEST_REVIEW_STATE

    def read(self, repository: Repository, argument: str) -> str:
        """
        :meth:`LibraryCall.read`, preceded by every line of :meth:`snapshot_text`.
        """
        source = ReadSource.detect()
        snapshot = source.reader(
            GitHubApi.from_environment(), repository, repository.owner
        ).read_current_state(int(argument))
        return (
            f"{self.snapshot_text(snapshot)}\n"
            f"read through {source}: {len(snapshot.threads)} review threads, "
            f"checks {self.verdict(snapshot)}"
        )

    @staticmethod
    def verdict(snapshot: UpstreamPullRequestSnapshot) -> str:
        """
        :param snapshot: A pull request's reviews, threads and checks.
        :return: Where its checks stand, as one word.
        """
        return str(snapshot.checks.state) if snapshot.checks else "not reported"

    def snapshot_text(self, snapshot: UpstreamPullRequestSnapshot) -> str:
        """
        :param snapshot: A pull request's reviews, threads and checks.
        :return: Each review, each thread with its state and comments, and the checks'
            verdict, one per line, texts written as JSON strings; the same for the
            same pull request however it was read.
        """
        lines = [f"checks {self.verdict(snapshot)}"]
        lines += [
            f"review {review.author.login} {review.state} {review.submitted_at} "
            f"{json.dumps(review.body)}"
            for review in snapshot.reviews
        ]
        for thread in snapshot.threads:
            lines.append(
                f"thread {thread.path}:{thread.line} resolved {thread.is_resolved} "
                f"outdated {thread.is_outdated}"
            )
            lines += [
                f"  comment {comment.author.login} {comment.created_at} "
                f"{json.dumps(comment.body)}"
                for comment in thread.comments
            ]
        return "\n".join(lines)


# %% entry point


def main() -> None:
    """
    Run the check the command line names and print what it read.
    """
    check, repository, *argument = sys.argv[1:]
    call = LibraryCall.from_check(LibraryCheck(check))
    print(call.read(Repository.parse(repository), "".join(argument)))


if __name__ == "__main__":
    main()
