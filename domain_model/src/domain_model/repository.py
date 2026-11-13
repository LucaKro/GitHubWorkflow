"""
A GitHub repository, identified the way GitHub itself writes it, and read out of the
references and git remote URLs the tooling is handed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlsplit

from domain_model.class_property import classproperty
from domain_model.exceptions import MalformedRepositoryError
from domain_model.number_links import HasNumberLink

# %% names GitHub gives a meaning


class ReservedRepositoryName(StrEnum):
    """
    The repository names GitHub reads something into.
    """

    COMMUNITY_HEALTH = ".github"
    """
    The owner's repository whose community health files, issue templates among them,
    apply to each of the owner's repositories lacking its own.
    """


# %% addresses


class GitHubAddress(StrEnum):
    """
    The base URLs every GitHub address this package builds is built on.
    """

    WEB = "https://github.com"
    """
    The root of every web and clone URL.
    """

    API = "https://api.github.com"
    """
    The root of every REST call.
    """


class RemoteHost(StrEnum):
    """
    The hosts a git remote URL naming a GitHub repository points at.
    """

    GITHUB = "github.com"
    """
    GitHub itself, over HTTPS or SSH.
    """

    LOOPBACK = "127.0.0.1"
    """
    This machine, where the proxy a cloud session reaches GitHub through answers under
    :attr:`proxy_prefix`.
    """

    LOCALHOST = "localhost"
    """
    This machine, by name.
    """

    @classproperty
    def proxy_prefix(cls) -> str:
        """
        The first path segment under which the local proxy serves GitHub's repositories.
        """
        return "git"


class RemoteScheme(StrEnum):
    """
    The URL schemes of a git remote that need no host to name a GitHub repository.
    """

    FILE = "file"
    """
    A directory of bare repositories on this machine, standing in for GitHub.
    """


# %% repositories and pull requests


@dataclass(frozen=True)
class Repository:
    """
    A GitHub repository, identified the way GitHub itself writes it.
    """

    owner: str
    """
    The user or organization the repository belongs to.
    """

    name: str
    """
    The repository's own name.
    """

    @classmethod
    def parse(cls, text: str) -> Repository:
        """
        Parse an ``owner/name`` repository reference.

        :param text: The reference to parse.
        :return: The parsed repository.
        :raises MalformedRepositoryError: If *text* is not ``owner/name``.
        """
        if not cls.is_full_name(text):
            raise MalformedRepositoryError(text)
        owner, _, name = text.partition("/")
        return cls(owner, name)

    @staticmethod
    def is_full_name(text: str) -> bool:
        """
        :param text: A value that may name a repository.
        :return: Whether *text* is an ``owner/name`` repository reference.
        """
        owner, separator, name = text.partition("/")
        return bool(owner and separator and name)

    @staticmethod
    def _remote_url_segments(url: str) -> list[str]:
        """
        :param url: A remote URL.
        :return: Its path segments, which name a repository when there are two or more;
            none when it points anywhere but GitHub, the local proxy to it, or a local
            directory standing in for it.
        """
        reference = url.removesuffix(".git").rstrip("/")
        if "://" not in reference:
            authority, separator, path = reference.partition(":")
            if not separator:
                return []
            reference = f"ssh://{authority}/{path}"
        address = urlsplit(reference)
        segments = [segment for segment in address.path.split("/") if segment]
        if address.scheme == RemoteScheme.FILE or address.hostname == RemoteHost.GITHUB:
            return segments
        on_this_machine = address.hostname in (
            RemoteHost.LOOPBACK,
            RemoteHost.LOCALHOST,
        )
        if on_this_machine and segments[:1] == [RemoteHost.proxy_prefix]:
            return segments[1:]
        return []

    @classmethod
    def names_a_repository(cls, url: str) -> bool:
        """
        Test whether a remote URL points at a repository at all.

        :param url: The remote URL to test.
        :return: Whether it names an ``owner/name`` pair.
        """
        return len(cls._remote_url_segments(url)) >= 2

    @classmethod
    def from_remote_url(cls, url: str) -> Repository:
        """
        Read the repository a git remote URL points at.

        Accepts every form a fork remote takes - HTTPS, SSH, the local proxy a cloud
        session is given, and a local directory standing in for GitHub - and takes the
        last two path segments.

        :param url: The remote URL to read.
        :return: The repository it names.
        :raises MalformedRepositoryError: If *url* names no ``owner/name`` pair.
        """
        segments = cls._remote_url_segments(url)
        if len(segments) < 2:
            raise MalformedRepositoryError(url)
        return cls.parse("/".join(segments[-2:]))

    @property
    def full_name(self) -> str:
        """
        The ``owner/name`` form GitHub's own interface and the ``gh`` CLI use.
        """
        return f"{self.owner}/{self.name}"

    @property
    def url(self) -> str:
        """
        The repository's page on GitHub, which is also the base of every page within it.
        """
        return f"{GitHubAddress.WEB}/{self.full_name}"

    @property
    def clone_url(self) -> str:
        """
        The HTTPS URL git clones and fetches the repository from.
        """
        return self.rooted_clone_url()

    def rooted_clone_url(self, root: str = GitHubAddress.WEB) -> str:
        """
        :param root: Where repositories are kept as ``<root>/owner/name.git``: GitHub
            itself, or a directory of bare repositories standing in for it.
        :return: The URL git clones and fetches this repository from there.
        """
        return f"{root}/{self.full_name}.git"

    def pull_request_url(self, number: int) -> str:
        """
        :param number: The pull request's number.
        :return: The pull request's page on GitHub.
        """
        return f"{self.url}/pull/{number}"

    def is_pull_request_page(self, url: str) -> bool:
        """
        :param url: An address.
        :return: Whether it is on the page of one of the repository's pull requests,
            such as a review comment's.
        """
        return url.startswith(self.pull_request_url(""))

    @property
    def settings_url(self) -> str:
        """:return: The repository's settings page on GitHub."""
        return f"{self.url}/settings"

    @property
    def actions_settings_url(self) -> str:
        """:return: The repository's settings page for GitHub Actions."""
        return f"{self.settings_url}/actions"

    @property
    def actions_url(self) -> str:
        """:return: The repository's page listing its Actions workflows and runs."""
        return f"{self.url}/actions"

    @property
    def community_health_repository(self) -> Repository:
        """
        The owner's repository whose community health files apply to this one where it
        lacks its own.
        """
        return Repository(self.owner, ReservedRepositoryName.COMMUNITY_HEALTH)

    def issue_url(self, number: int) -> str:
        """
        :param number: An issue or pull request of the repository.
        :return: Its page on GitHub; GitHub opens a pull request's own page from it.
        """
        return f"{self.url}/issues/{number}"

    def issue_link(self, number: int) -> str:
        """
        :param number: An issue or pull request of the repository.
        :return: Its number, as GitHub's Markdown links it to its page.
        """
        return HasNumberLink.link_format.format(
            number=number, url=self.issue_url(number)
        )

    def workflow_run_url(self, run: int) -> str:
        """
        :param run: The Actions workflow run's own number.
        :return: The run's page on GitHub.
        """
        return f"{self.actions_url}/runs/{run}"

    @property
    def api_path(self) -> str:
        """
        The repository's REST path, relative to :attr:`GitHubAddress.API`, which is also
        the base of every REST path within it and what ``gh api`` takes.
        """
        return f"repos/{self.full_name}"

    def job_log_path(self, job: int) -> str:
        """
        :param job: The Actions job's own number.
        :return: The REST path of that job's whole recorded log.
        """
        return f"{self.api_path}/actions/jobs/{job}/logs"

    def git_requirement(
        self, distribution: str, reference: str, subdirectory: str | None = None
    ) -> str:
        """
        A pip requirement installing a distribution straight from this repository.

        :param distribution: The distribution the repository builds.
        :param reference: The tag, branch or commit to install it at.
        :param subdirectory: The directory holding the distribution's project,
            ``None`` for the repository's root.
        :return: The requirement, as ``pip install`` takes it.
        """
        requirement = f"{distribution} @ git+{self.url}@{reference}"
        if subdirectory is None:
            return requirement
        return f"{requirement}#subdirectory={subdirectory}"

    def __str__(self) -> str:
        """:return: :attr:`full_name`."""
        return self.full_name


@dataclass(frozen=True)
class PullRequestReference:
    """
    One pull request, named by the repository it is opened on and its number.

    Identity only: what a pull request currently *is* - open, merged, labelled - is read
    into a record of its own by whichever caller needs it.
    """

    repository: Repository
    """
    The repository the pull request is opened on.
    """

    number: int
    """
    The pull request's number.
    """

    @property
    def url(self) -> str:
        """
        The pull request's page on GitHub.
        """
        return self.repository.pull_request_url(self.number)
