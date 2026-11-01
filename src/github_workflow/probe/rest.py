"""
Calling GitHub's REST API through ``curl``, so a refused call is a result to record
rather than an error to handle.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

from basstler_domain_model.class_property import classproperty
from basstler_domain_model.environment import GitHubCredentialVariable
from basstler_domain_model.github.vocabulary import PullRequestJSONKey
from basstler_domain_model.repository import GitHubAddress, Repository

from github_workflow.probe.commands import CommandResult, CommandRunner

# %% vocabulary


class HttpMethod(StrEnum):
    """
    The HTTP methods the probe calls the API with.
    """

    GET = "GET"
    POST = "POST"
    PATCH = "PATCH"
    PUT = "PUT"
    DELETE = "DELETE"


# %% a response


@dataclass(frozen=True)
class RestResponse:
    """
    One answer from the API, or the reason there was none.
    """

    status: int
    """
    The HTTP status, ``0`` when no response arrived.
    """

    body: Any
    """
    The decoded JSON body, or its raw text when it is not JSON.
    """

    seconds: float
    """
    How long the call took.
    """

    @classproperty
    def status_separator(cls) -> str:
        """
        What ``curl`` writes between the body and the status it appends.
        """
        return "\n"

    @classmethod
    def from_command(cls, result: CommandResult) -> RestResponse:
        """
        :param result: The finished ``curl``, which appended the status to the body.
        :return: The response.
        """
        if not result.succeeded:
            return cls(0, result.error_output, result.seconds)
        text, _, status = result.output.rpartition(cls.status_separator)
        return cls(int(status), cls._decoded(text), result.seconds)

    @staticmethod
    def _decoded(text: str) -> Any:
        """
        :param text: A response body.
        :return: It decoded as JSON, or as it came when it is not JSON.
        """
        if not text.strip().startswith(("{", "[")):
            return text
        return json.loads(text)

    @property
    def succeeded(self) -> bool:
        """:return: Whether the API answered with a 2xx status."""
        return 200 <= self.status < 300

    @property
    def summary(self) -> str:
        """:return: The API's own message on a refusal, a count for a list, else
        nothing."""
        if isinstance(self.body, dict) and PullRequestJSONKey.MESSAGE in self.body:
            return str(self.body[PullRequestJSONKey.MESSAGE])
        if isinstance(self.body, list):
            return f"{len(self.body)} entries"
        if isinstance(self.body, str):
            return self.body[:200]
        return ""


# %% making a call


@dataclass(frozen=True)
class RestCaller:
    """
    Calls the API through ``curl``, with a token when the environment carries one.
    """

    runner: CommandRunner
    """
    Runs ``curl``.
    """

    def call(
        self, method: HttpMethod, path: str, payload: dict[str, Any] | None = None
    ) -> RestResponse:
        """
        :param method: The HTTP method.
        :param path: The path below the API root, starting with a slash.
        :param payload: The JSON body, absent for a read.
        :return: The answer.
        """
        with tempfile.TemporaryDirectory() as directory:
            headers = Path(directory) / "headers"
            headers.write_text(self._headers())
            arguments = [
                "curl",
                "--silent",
                "--show-error",
                "--request",
                method,
                "--header",
                f"@{headers}",
                "--write-out",
                f"{RestResponse.status_separator}%{{http_code}}",
            ]
            if payload is not None:
                arguments += ["--data-binary", "@-"]
            result = self.runner.run(
                *arguments,
                f"{GitHubAddress.API}{path}",
                standard_input=None if payload is None else json.dumps(payload),
            )
        return RestResponse.from_command(result)

    @staticmethod
    def _headers() -> str:
        """
        :return: The request headers, one per line, the token's included when one is set.
        """
        lines = [
            "Accept: application/vnd.github+json",
            "X-GitHub-Api-Version: 2022-11-28",
            "Content-Type: application/json",
        ]
        token = GitHubCredentialVariable.first_token()
        if token:
            lines.append(f"Authorization: Bearer {token}")
        return "\n".join(lines) + "\n"


# %% the paths


@dataclass(frozen=True)
class RepositoryRoute:
    """
    The REST paths the probe calls, below one repository and beside it.
    """

    repository: Repository
    """
    The repository the session works in.
    """

    @property
    def root(self) -> str:
        """:return: The repository itself."""
        return f"/repos/{self.repository.full_name}"

    def issues(self, **filters: str) -> str:
        """
        :param filters: Query parameters narrowing the listing.
        :return: The repository's issues.
        """
        query = f"?{urlencode(filters)}" if filters else ""
        return f"{self.root}/issues{query}"

    def issue(self, number: int) -> str:
        """:param number: The issue.
        :return: That issue."""
        return f"{self.root}/issues/{number}"

    def issue_comments(self, number: int) -> str:
        """:param number: The issue.
        :return: Its comments."""
        return f"{self.issue(number)}/comments"

    @property
    def labels(self) -> str:
        """:return: The repository's labels."""
        return f"{self.root}/labels"

    def label(self, name: str) -> str:
        """:param name: The label.
        :return: That label."""
        return f"{self.labels}/{quote(name)}"

    @property
    def pull_requests(self) -> str:
        """:return: The repository's pull requests."""
        return f"{self.root}/pulls"

    def pull_request(self, number: int) -> str:
        """:param number: The pull request.
        :return: That pull request."""
        return f"{self.pull_requests}/{number}"

    def review_threads(self, number: int) -> str:
        """
        :param number: The pull request.
        :return: Its review threads, through the cloud session proxy's own route.
        """
        return f"{self.pull_request(number)}/ccr/review_threads"

    @property
    def actions_permissions(self) -> str:
        """:return: Whether Actions may run in the repository, and which."""
        return f"{self.root}/actions/permissions"

    def workflow_runs(self, branch: str) -> str:
        """:param branch: The branch the runs were triggered on.
        :return: Its workflow runs, newest first."""
        return f"{self.root}/actions/runs?{urlencode({'branch': branch})}"

    def comparison(self, base: str, head: str) -> str:
        """
        :param base: The branch compared against.
        :param head: The branch compared.
        :return: How far *head* is ahead of and behind *base*.
        """
        return f"{self.root}/compare/{quote(base)}...{quote(head)}"

    def check_runs(self, commit: str) -> str:
        """:param commit: The commit.
        :return: The check runs reported on it."""
        return f"{self.root}/commits/{commit}/check-runs"

    @staticmethod
    def review_requests() -> str:
        """
        :return: The search for open pull requests waiting on the caller's review.
        """
        return (
            f"/search/issues?{urlencode({'q': 'is:open is:pr review-requested:@me'})}"
        )
