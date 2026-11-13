"""
Which remote of a checkout the workflow may write to - only one pointing at a repository
of the owner's - and which one it reads the repository the owner's fork was forked from
through.
"""

from __future__ import annotations

from dataclasses import dataclass

from domain_model.git.commands import GitCommandRunner
from domain_model.git.remotes import Remote, RemoteName, UnconfiguredRemote
from domain_model.repository import Repository

from github_workflow.exceptions import (
    AmbiguousOwnedRemoteError,
    NoOwnedRemoteError,
    UpstreamRemoteNameTakenError,
)
from github_workflow.settings import WorkflowSettings

# %% one remote


@dataclass(frozen=True)
class OwnedRemote(Remote):
    """
    A remote whose push URL points at a repository of the owner's.
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
        remotes = Remote.read_configured(git)
        owned = tuple(
            OwnedRemote(remote.git, remote.name, remote.push_url, remote.repository)
            for remote in remotes
            if remote.repository is not None and settings.owns(remote.repository)
        )
        return cls(owned, tuple(remote.name for remote in remotes), settings.owner)

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
        problem = self.problem
        if problem is not None:
            raise problem
        return next(
            (remote for remote in self.owned if remote.name == RemoteName.ORIGIN),
            self.owned[0],
        )


# %% the upstream of a fork


@dataclass(frozen=True)
class ForkUpstream:
    """
    The repository the owner's fork was forked from, as a checkout of the fork reaches
    it.
    """

    git: GitCommandRunner
    """
    Runs git in the checkout of the fork.
    """

    repository: Repository
    """
    The repository the fork was forked from.
    """

    def remote(self) -> Remote:
        """
        :return: The checkout's remote reaching it, the one named
            :attr:`RemoteName.UPSTREAM` first; when none does, the upstream reached by
            its URL under that name.
        :raises UpstreamRemoteNameTakenError: If none reaches it and the remote of that
            name reaches another repository.
        """
        configured = Remote.read_configured(self.git)
        reaching = [
            remote for remote in configured if remote.repository == self.repository
        ]
        named = [remote for remote in reaching if remote.name == RemoteName.UPSTREAM]
        if named or reaching:
            return (named or reaching)[0]
        taken = [remote for remote in configured if remote.name == RemoteName.UPSTREAM]
        if taken:
            raise UpstreamRemoteNameTakenError(taken[0], self.repository)
        url = self.repository.rooted_clone_url()
        return UnconfiguredRemote(self.git, RemoteName.UPSTREAM, url, self.repository)
