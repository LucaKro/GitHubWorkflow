"""
The interfaces through which GitHub is read, and the client implementing them over HTTP.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from http import HTTPMethod, HTTPStatus
from pathlib import Path
from typing import Any

from domain_model.class_property import classproperty
from domain_model.commands import CommandRunner
from domain_model.environment import GitHubActionsVariable
from domain_model.github.credential import GitHubToken
from domain_model.github.exceptions import GitHubRequestFailed
from domain_model.github.pull_request_models import GraphQLResponse
from domain_model.github.vocabulary import PullRequestJSONKey
from domain_model.repository import GitHubAddress, Repository

# %% what reads GitHub


class JobLogReader(ABC):
    """
    Reads the log one Actions job recorded.
    """

    @abstractmethod
    def read_job_log(self, repository: Repository, job_identifier: int) -> str:
        """
        Read one job's whole log.

        :param repository: The repository the job ran in.
        :param job_identifier: The job to read.
        :return: The log, exactly as the runner recorded it.
        """


class GraphQLClient(ABC):
    """
    Sends a GraphQL document to GitHub and returns its ``data`` member.
    """

    @abstractmethod
    def execute(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        """
        Run one GraphQL query.

        :param query: The GraphQL document.
        :param variables: The document's variables.
        :return: The response's ``data`` member.
        """


class RestClient(ABC):
    """
    Reads REST responses from GitHub.
    """

    @abstractmethod
    def get(self, path: str) -> Any:
        """
        Read one response.

        :param path: The REST path, query included.
        :return: The parsed response.
        """

    @abstractmethod
    def get_pages(self, path: str) -> list[Any]:
        """
        Read every page of a paged response.

        :param path: The REST path of the first page, query included.
        :return: Each page's parsed response, in order.
        """


class GitHubReader(RestClient, GraphQLClient, ABC):
    """
    Reads GitHub over REST and GraphQL alike.
    """


class RestWriter(ABC):
    """
    Makes REST calls to GitHub, writes included.
    """

    @abstractmethod
    def attempt(
        self, method: str, path: str, payload: Mapping[str, Any] | None = None
    ) -> RestAnswer:
        """
        Make one call whose refusal is an expected outcome.

        :param method: The HTTP method.
        :param path: The path below the API root, or a whole address the API handed out.
        :param payload: The JSON body, absent for a read.
        :return: What the API answered, a refusal included.
        """

    @abstractmethod
    def request(
        self, method: str, path: str, payload: Mapping[str, Any] | None = None
    ) -> Any:
        """
        Make one call the caller depends on.

        :param method: The HTTP method.
        :param path: The path below the API root.
        :param payload: The JSON body, absent for a read.
        :return: The decoded answer, ``None`` when it has no body.
        :raises GitHubRequestFailed: If the API refuses the call.
        """


class RestApi(RestClient, RestWriter, ABC):
    """
    GitHub's REST API, read and written.
    """


# %% one answer


@dataclass(frozen=True)
class RestAnswer:
    """
    What the API answered one call with, a refusal included.
    """

    status: int
    """
    The HTTP status.
    """

    text: str
    """
    The body, as it came.
    """

    headers: Mapping[str, str] = field(default_factory=dict)
    """
    The response headers, by lowercased name.
    """

    @classproperty
    def redirect_statuses(cls) -> frozenset[int]:
        """
        The statuses that send a caller to another address.
        """
        return frozenset(
            {
                HTTPStatus.MOVED_PERMANENTLY,
                HTTPStatus.FOUND,
                HTTPStatus.SEE_OTHER,
                HTTPStatus.TEMPORARY_REDIRECT,
                HTTPStatus.PERMANENT_REDIRECT,
            }
        )

    @property
    def succeeded(self) -> bool:
        """:return: Whether the status is a 2xx one."""
        return HTTPStatus.OK <= self.status < HTTPStatus.MULTIPLE_CHOICES

    @property
    def refused(self) -> bool:
        """:return: Whether GitHub refused the call to the credential: forbidden, or
        hidden from it as not found."""
        return self.status in {HTTPStatus.FORBIDDEN, HTTPStatus.NOT_FOUND}

    def raise_if_failed(self, method: str, path: str) -> RestAnswer:
        """
        :param method: The HTTP method of the call this answers.
        :param path: The path it was made to.
        :return: This answer, when it succeeded.
        :raises GitHubRequestFailed: When it did not.
        """
        if not self.succeeded:
            raise GitHubRequestFailed(
                status=self.status, detail=self.text, method=method, path=path
            )
        return self

    @property
    def body(self) -> Any:
        """:return: The body decoded as JSON, ``None`` when it is empty."""
        return json.loads(self.text) if self.text else None

    @property
    def redirect(self) -> str | None:
        """:return: The address the answer sends the caller to, ``None`` when it sends
        it nowhere."""
        if self.status not in self.redirect_statuses:
            return None
        return self.headers.get("location")

    @classproperty
    def method_keeping_redirect_statuses(cls) -> frozenset[int]:
        """
        The redirects that are followed with the method and body of the call they
        answer.
        """
        return frozenset({HTTPStatus.TEMPORARY_REDIRECT, HTTPStatus.PERMANENT_REDIRECT})

    def follow_up_method(self, method: str) -> str | None:
        """
        :param method: The HTTP method of the call this answers.
        :return: The method to call :attr:`redirect` with, ``None`` when the answer is
            not to be followed: a write moved by 301 or 302 is never turned into a read.
        """
        if self.redirect is None:
            return None
        if (
            method == HTTPMethod.GET
            or self.status in self.method_keeping_redirect_statuses
        ):
            return method
        if self.status == HTTPStatus.SEE_OTHER:
            return HTTPMethod.GET
        return None

    @property
    def next_page(self) -> str | None:
        """:return: The address of the next page of a paged listing, ``None`` on the
        last page."""
        found = re.search(r'<([^>]+)>;\s*rel="next"', self.headers.get("link", ""))
        return found.group(1) if found else None


# %% the client


class NoAutomaticRedirect(urllib.request.HTTPRedirectHandler):
    """
    Hands every redirect back as an answer, so the client decides whether the token
    travels with it.
    """

    def redirect_request(self, *arguments: Any) -> None:
        """:return: Nothing, so the redirect is answered rather than followed."""
        return None


@dataclass(frozen=True)
class GitHubApi(GitHubReader, RestApi, JobLogReader):
    """
    GitHub's REST and GraphQL APIs, called over HTTP with a token.
    """

    token: str
    """
    The credential the calls authenticate with.
    """

    api_root: str = GitHubAddress.API
    """
    Where the API answers.
    """

    timeout_seconds: float = 30.0
    """
    How long a call may wait on the API before it fails.
    """

    @classmethod
    def from_environment(cls) -> GitHubApi:
        """
        :return: A client with the environment's token, or ``gh``'s, at the API root a
            GitHub Actions runner names, or GitHub's own.
        :raises GitHubCredentialUnavailableError: If no token is found.
        """
        return cls(
            GitHubToken(CommandRunner(Path.cwd())).find(),
            GitHubActionsVariable.API_URL.read() or GitHubAddress.API,
        )

    def attempt(
        self, method: str, path: str, payload: Mapping[str, Any] | None = None
    ) -> RestAnswer:
        """
        Follows a redirect as :meth:`RestAnswer.follow_up_method` says, with the token
        only when it stays on the API's host; see :meth:`RestWriter.attempt`.
        """
        address = (
            path
            if path.startswith(self.api_root)
            else f"{self.api_root}/{path.removeprefix('/')}"
        )
        answer = self._exchange(method, address, payload, authorized=True)
        follow_up = answer.follow_up_method(method)
        if follow_up is None:
            return answer
        target = urllib.parse.urljoin(address, answer.redirect)
        same_host = (
            urllib.parse.urlsplit(target).netloc
            == urllib.parse.urlsplit(self.api_root).netloc
        )
        return self._exchange(
            follow_up,
            target,
            payload if follow_up == method else None,
            authorized=same_host,
        )

    def request(
        self, method: str, path: str, payload: Mapping[str, Any] | None = None
    ) -> Any:
        return self.attempt(method, path, payload).raise_if_failed(method, path).body

    def execute(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        """
        :raises GitHubRequestFailed: If the API refuses the call.
        :raises GraphQLErrorsReturned: If GitHub answers with errors.
        """
        payload = {
            PullRequestJSONKey.QUERY: query,
            PullRequestJSONKey.VARIABLES: variables,
        }
        answer = self.attempt("POST", "graphql", payload).raise_if_failed(
            "POST", "graphql"
        )
        return GraphQLResponse.from_json(answer.text).result()

    def get(self, path: str) -> Any:
        """
        :raises GitHubRequestFailed: If the API refuses the call.
        """
        return self.request("GET", path)

    def get_pages(self, path: str) -> list[Any]:
        """
        Reads every page at the first page's path, taking only the query from each
        page's next link; see :meth:`RestClient.get_pages`.

        :raises GitHubRequestFailed: If the API refuses a page.
        """
        listing = urllib.parse.urlsplit(path)
        pages = []
        address: str | None = path
        while address is not None:
            answer = self.attempt("GET", address).raise_if_failed("GET", address)
            pages.append(answer.body)
            next_page = answer.next_page
            address = (
                None
                if next_page is None
                else listing._replace(
                    query=urllib.parse.urlsplit(next_page).query
                ).geturl()
            )
        return pages

    def read_job_log(self, repository: Repository, job_identifier: int) -> str:
        """
        :raises GitHubRequestFailed: If the API refuses the call.
        """
        path = repository.job_log_path(job_identifier)
        return self.attempt("GET", path).raise_if_failed("GET", path).text

    def _exchange(
        self,
        method: str,
        address: str,
        payload: Mapping[str, Any] | None,
        authorized: bool,
    ) -> RestAnswer:
        """
        :param method: The HTTP method.
        :param address: The whole address to call.
        :param payload: The JSON body, absent for a read.
        :param authorized: Whether the token goes with the call.
        :return: What came back, a refusal or a redirect included.
        :raises GitHubRequestFailed: If no answer came back.
        """
        headers = {
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        }
        if authorized:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(
            address,
            method=method,
            data=None if payload is None else json.dumps(payload).encode(),
            headers=headers,
        )
        opener = urllib.request.build_opener(NoAutomaticRedirect())
        try:
            with opener.open(request, timeout=self.timeout_seconds) as response:
                return RestAnswer(
                    response.status,
                    response.read().decode(errors="replace"),
                    {name.lower(): value for name, value in response.headers.items()},
                )
        except urllib.error.HTTPError as refused:
            return RestAnswer(
                refused.code,
                refused.read().decode(errors="replace"),
                {
                    name.lower(): value
                    for name, value in (refused.headers or {}).items()
                },
            )
        except (urllib.error.URLError, TimeoutError) as unanswered:
            raise GitHubRequestFailed(
                status=None,
                detail=str(unanswered),
                method=method,
                path=address,
            ) from unanswered
