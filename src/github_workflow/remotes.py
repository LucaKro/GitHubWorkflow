"""
Which remote of a checkout the workflow may write to: only one pointing at a repository
of the owner's.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from basstler_domain_model.git.commands import GitCommandRunner
from basstler_domain_model.repository import Repository

from github_workflow.exceptions import AmbiguousOwnedRemoteError, NoOwnedRemoteError
from github_workflow.settings import WorkflowSettings

# %% vocabulary


class RemoteName(StrEnum):
    """
    The remote names the workflow treats specially.
    """

    ORIGIN = "origin"
    """
    The remote a clone starts with, preferred when several are the owner's.
    """


# %% one remote


@dataclass(frozen=True)
class OwnedRemote:
    """
    A remote whose push URL points at a repository of the owner's.
    """

    name: str
    """
    The remote's name in the checkout.
    """

    repository: Repository
    """
    The repository its push URL points at.
    """


# %% every remote


@dataclass(frozen=True)
class OwnedRemotes:
    """
    The checkout's remotes that point at the owner's repositories, and the one to use.
    """

    owned: tuple[OwnedRemote, ...]
    """
    Every remote whose push URL points at a repository of the owner's.
    """

    remote_names: tuple[str, ...]
    """
    Every remote the checkout has.
    """

    owner: str
    """
    The account whose repositories alone are written to.
    """

    @classmethod
    def read(cls, git: GitCommandRunner, settings: WorkflowSettings) -> OwnedRemotes:
        """
        :param git: Runs git in the checkout.
        :param settings: Whose repositories count as owned.
        :return: The checkout's remotes, sorted into owned and the rest.
        """
        names = tuple(git.run("remote").split())
        owned = []
        for name in names:
            url = git.run("remote", "get-url", "--push", name)
            if not Repository.names_a_repository(url):
                continue
            repository = Repository.from_remote_url(url)
            if repository.owner.casefold() == settings.owner.casefold():
                owned.append(OwnedRemote(name, repository))
        return cls(tuple(owned), names, settings.owner)

    @property
    def problem(self) -> NoOwnedRemoteError | AmbiguousOwnedRemoteError | None:
        """
        :return: Why no remote can be chosen, ``None`` when one can.
        """
        names = tuple(remote.name for remote in self.owned)
        if not names:
            return NoOwnedRemoteError(self.owner, self.remote_names)
        if len(names) > 1 and RemoteName.ORIGIN not in names:
            return AmbiguousOwnedRemoteError(self.owner, names)
        return None

    @property
    def chosen(self) -> OwnedRemote:
        """
        :return: ``origin`` when it is owned, otherwise the only owned remote.
        :raises NoOwnedRemoteError: If no remote is owned.
        :raises AmbiguousOwnedRemoteError: If several are, and none is ``origin``.
        """
        if self.problem is not None:
            raise self.problem
        return next(
            (remote for remote in self.owned if remote.name == RemoteName.ORIGIN),
            self.owned[0],
        )
