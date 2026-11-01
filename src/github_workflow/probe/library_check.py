"""
One call through :mod:`basstler_domain_model`, run as a process of its own so a refusal
ends only this check, with the library's own error as its message.

Usage: ``python -m github_workflow.probe.library_check <check> <owner/name>
[<argument>]``
"""

from __future__ import annotations

import sys
from enum import StrEnum

from basstler_domain_model.github.clients import GitHubCommandLineClient
from basstler_domain_model.github.readers import ReadSource
from basstler_domain_model.github.repository_client import GitHubRepository
from basstler_domain_model.repository import Repository

# %% the checks


class LibraryCheck(StrEnum):
    """
    The calls through the library a probe makes, each printing what it read in one line.
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

    def run(self, repository: Repository, argument: str) -> str:
        """
        :param repository: The repository the session works in.
        :param argument: The commit or pull request number the check needs, if any.
        :return: What it read, in one line.
        """
        if self is LibraryCheck.PULL_REQUEST_REVIEW_STATE:
            source = ReadSource.detect()
            snapshot = source.reader(
                GitHubCommandLineClient(), repository, repository.owner
            ).read_current_state(int(argument))
            checks = snapshot.checks.state if snapshot.checks else "not reported"
            return (
                f"read through {source}: {len(snapshot.threads)} review threads, "
                f"checks {checks}"
            )
        client = GitHubRepository.from_environment(repository)
        match self:
            case LibraryCheck.AUTHENTICATED_LOGIN:
                return client.authenticated_login()
            case LibraryCheck.LABELS:
                return ", ".join(sorted(client.labels()))
            case LibraryCheck.OPEN_PULL_REQUESTS:
                return f"{len(client.open_pull_requests())} open"
            case LibraryCheck.CHECK_STATE:
                return str(client.check_state(argument))


# %% entry point


def main() -> None:
    """
    Run the check the command line names and print what it read.
    """
    check, repository, *argument = sys.argv[1:]
    print(LibraryCheck(check).run(Repository.parse(repository), "".join(argument)))


if __name__ == "__main__":
    main()
