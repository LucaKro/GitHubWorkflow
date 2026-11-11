"""
A checkout's remotes, their branches and what a fetch of them keeps, and every push,
built as a :class:`ProposedPush` so whether published history may be rewritten is
decided in one place.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields
from enum import StrEnum

from domain_model.git.commands import GitCommandResult, GitCommandRunner
from domain_model.git.exceptions import MalformedReferenceUpdateError
from domain_model.git.revisions import CommitHash, ReferenceNamespace, Revision
from domain_model.repository import Repository

# %% remotes


class RemoteName(StrEnum):
    """
    The remote names git gives a meaning of their own.
    """

    ORIGIN = "origin"
    """
    The remote a clone starts with.
    """

    UPSTREAM = "upstream"
    """
    The remote a fork's checkout reaches the repository it was forked from by.
    """


@dataclass(frozen=True)
class Remote:
    """
    One remote of a checkout, and the GitHub repository it pushes to.
    """

    git: GitCommandRunner
    """
    Runs git in the checkout the remote belongs to.
    """

    name: str
    """
    The remote's name, under which the checkout keeps its remote-tracking branches.
    """

    push_url: str
    """
    The URL a push to it goes to.
    """

    repository: Repository | None
    """
    The repository the push URL names, ``None`` when it names none.
    """

    fetch_url: str | None = None
    """
    The URL it is reached at when the checkout configures no remote of its name,
    ``None`` to reach it by its name.
    """

    @classmethod
    def configured(cls, git: GitCommandRunner) -> list[Remote]:
        """
        :param git: Runs git in a checkout.
        :return: Every remote the checkout configures, in the order git lists them.
        """
        return [
            cls.from_push_url(git, name, git.run("remote", "get-url", "--push", name))
            for name in git.run("remote").split()
        ]

    @classmethod
    def from_push_url(cls, git: GitCommandRunner, name: str, url: str) -> Remote:
        """
        :param git: Runs git in a checkout.
        :param name: The remote's name, or the URL git was given when the push names no
            remote.
        :param url: The URL a push to it goes to.
        :return: The remote, with the repository its URL names.
        """
        repository = (
            Repository.from_remote_url(url)
            if Repository.names_a_repository(url)
            else None
        )
        return cls(git, name, url, repository)

    @property
    def location(self) -> str:
        """:return: How git is told to reach the remote: its URL, or its name."""
        return self.fetch_url or self.name

    def branch(self, name: str) -> RemoteBranch:
        """
        :param name: A branch's name.
        :return: The branch of that name on this remote.
        """
        return RemoteBranch(self, name)

    def fetch(self, *branches: str) -> None:
        """
        Refresh what the checkout knows about the remote.

        :param branches: The branches to fetch, by name; all of them when none is named.
        :raises GitCommandFailed: If the remote cannot be reached.
        """
        self.git.run("fetch", "--quiet", self.location, *branches)

    def branch_tips(self) -> dict[str, CommitHash]:
        """
        :return: Each branch the remote has, by its name, and the commit it is at.
        :raises GitCommandFailed: If the remote cannot be reached.
        """
        listed = self.git.run("ls-remote", "--heads", self.location)
        return {
            reference.removeprefix(ReferenceNamespace.BRANCHES): CommitHash(commit)
            for commit, reference in (line.split() for line in listed.splitlines())
        }

    def default_branch(self) -> str | None:
        """
        :return: The branch the remote's ``HEAD`` names, as the remote answers, or as
            last fetched when it cannot be reached; ``None`` when neither knows.
        """
        branches = ReferenceNamespace.BRANCHES
        listed = self.git.attempt("ls-remote", "--symref", self.location, "HEAD")
        for line in listed.output.splitlines() if listed.succeeded else []:
            target, _, name = line.partition("\t")
            if name == "HEAD" and target.startswith(f"ref: {branches}"):
                return target.removeprefix(f"ref: {branches}")
        tracking = f"{ReferenceNamespace.REMOTE_TRACKING_BRANCHES}{self.name}/"
        fetched = self.git.attempt("symbolic-ref", "--quiet", f"{tracking}HEAD")
        if not fetched.succeeded:
            return None
        return fetched.output.removeprefix(tracking)

    def delete_branches(self, tips: Mapping[str, CommitHash]) -> list[str]:
        """
        Delete branches from the remote in one push, each only while it is still at the
        commit given.

        :param tips: Each branch to delete, by name, and the commit it must still be at.
        :return: The branches not deleted, in the order given: those that moved, and
            those the remote refused.
        """
        if not tips:
            return []
        references = {name: self.branch(name).reference for name in tips}
        leases = [
            f"--force-with-lease={references[name]}:{commit}"
            for name, commit in tips.items()
        ]
        deletions = [f":{reference}" for reference in references.values()]
        pushed = self.git.attempt(
            "push", "--porcelain", *leases, self.location, *deletions
        )
        deleted = {
            columns[1].partition(":")[2]
            for columns in (
                line.split("\t") for line in pushed.standard_output.splitlines()
            )
            if len(columns) > 1 and columns[0] == PushFlag.DELETED
        }
        return [name for name in tips if references[name] not in deleted]


# %% a branch on a remote


class TrackingReferenceWrite(StrEnum):
    """
    How the reflog names a write of a remote-tracking branch from its remote, compared
    as the start of the entry.
    """

    FETCH = "fetch"
    """
    A fetch stored the branch.
    """

    PULL = "pull"
    """
    A pull stored the branch.
    """

    PUSH = "update by push"
    """
    A push sent the branch.
    """


@dataclass(frozen=True)
class RemoteBranch:
    """
    One branch on one remote, as the remote has it now.
    """

    remote: Remote
    """
    The remote it is on.
    """

    name: str
    """
    The branch's name on the remote.
    """

    @property
    def reference(self) -> str:
        """:return: The branch's full reference, as the remote has it."""
        return f"{ReferenceNamespace.BRANCHES}{self.name}"

    @property
    def tracking_branch(self) -> RemoteTrackingBranch:
        """:return: Where the checkout keeps the branch as last fetched."""
        return RemoteTrackingBranch(self)

    def fetch(self) -> GitCommandResult:
        """
        Fetch the branch into its remote-tracking branch, leaving ``FETCH_HEAD`` alone.

        :return: The finished fetch, whose failure is an expected outcome.
        """
        return self.remote.git.attempt(
            "fetch",
            "--quiet",
            "--no-write-fetch-head",
            self.remote.location,
            f"+{self.reference}:{self.tracking_branch.revision_name}",
        )

    def tip(self) -> CommitHash | None:
        """
        :return: The commit the branch is at on the remote, ``None`` when the remote has
            no such branch.
        :raises GitCommandFailed: If the remote cannot be reached.
        """
        listed = self.remote.git.run("ls-remote", self.remote.location, self.reference)
        return next(
            (
                CommitHash(commit)
                for commit, reference in (line.split() for line in listed.splitlines())
                if reference == self.reference
            ),
            None,
        )

    def exists(self) -> bool:
        """
        :return: Whether the remote has the branch.
        :raises GitCommandFailed: If the remote cannot be reached.
        """
        return self.tip() is not None

    def delete(self) -> GitCommandResult:
        """:return: The finished push deleting the branch, whose failure the caller
        reports."""
        return ProposedPush(self, None).publish()


@dataclass(frozen=True)
class RemoteTrackingBranch(Revision):
    """
    A branch of a remote as the checkout last fetched it, which may lag the remote or
    not exist yet.
    """

    branch: RemoteBranch
    """
    The branch on the remote.
    """

    @property
    def git(self) -> GitCommandRunner:
        """:return: Runs git in the checkout the branch was fetched into."""
        return self.branch.remote.git

    @property
    def revision_name(self) -> str:
        return (
            f"{ReferenceNamespace.REMOTE_TRACKING_BRANCHES}"
            f"{self.branch.remote.name}/{self.branch.name}"
        )

    def delete(self) -> None:
        """
        Forget the branch as last fetched, as when the remote no longer has it.
        """
        self.git.attempt("update-ref", "-d", self.revision_name)

    def was_fetched_or_pushed(self) -> bool:
        """:return: Whether a fetch, a pull or a push ever wrote it, as its reflog says."""
        reflog = self.git.attempt("reflog", "show", "--format=%gs", self.revision_name)
        entries = reflog.output.splitlines() if reflog.succeeded else []
        writes = tuple(TrackingReferenceWrite)
        return any(entry.startswith(writes) for entry in entries)


# %% what a push is allowed to overwrite


class PushFlag(StrEnum):
    """
    The flag ``git push --porcelain`` starts each reference's line with.
    """

    DELETED = "-"
    """
    The reference was deleted.
    """


@dataclass(frozen=True)
class ProposedPush:
    """
    One publication, and whether it is authorised to overwrite what is published.

    Every push is built here, so whether history may be rewritten is decided once rather
    than at each call.
    """

    destination: RemoteBranch
    """
    The branch on the remote that the push changes.
    """

    source: Revision | None
    """
    What the branch is set to, ``None`` to delete it.
    """

    with_lease: bool = False
    """
    Whether published history may be overwritten, and then only if the remote is where
    this checkout last saw it.
    """

    sets_upstream: bool = False
    """
    Whether the local branch published then tracks the branch it was published to.
    """

    runs_push_hook: bool = True
    """
    Whether the checkout's ``pre-push`` hook may refuse the push.
    """

    @property
    def refspec(self) -> str:
        """:return: What the push publishes, as ``<source>:<destination>``."""
        source = "" if self.source is None else self.source.revision_name
        return f"{source}:{self.destination.reference}"

    def publish(self) -> GitCommandResult:
        """
        Run the push, forcing only where it says it is authorised.

        :return: The finished push, whose failure the caller reports rather than forces.
        """
        lease = ["--force-with-lease"] if self.with_lease else []
        upstream = ["--set-upstream"] if self.sets_upstream else []
        hook = [] if self.runs_push_hook else ["--no-verify"]
        remote = self.destination.remote
        return remote.git.attempt(
            "push", "--quiet", *lease, *upstream, *hook, remote.location, self.refspec
        )


# %% what a push changes


@dataclass(frozen=True)
class ReferenceUpdate:
    """
    One reference a push is about to change, as git describes it to a ``pre-push``
    hook.
    """

    local_reference: str
    """
    The local reference pushed, ``(delete)`` when the push deletes the remote one.
    """

    local_commit: CommitHash
    """
    The commit pushed, all zeros when the push deletes.
    """

    remote_reference: str
    """
    The reference on the remote that the push changes.
    """

    remote_commit: CommitHash
    """
    The commit the remote reference is at, all zeros when it does not exist yet.
    """

    @classmethod
    def from_line(cls, line: str) -> ReferenceUpdate:
        """
        :param line: One line of a ``pre-push`` hook's input.
        :return: The update it describes.
        :raises MalformedReferenceUpdateError: If the line does not hold one field per
            attribute.
        """
        words = line.split()
        if len(words) != len(fields(cls)):
            raise MalformedReferenceUpdateError(line)
        local_reference, local_commit, remote_reference, remote_commit = words
        return cls(
            local_reference,
            CommitHash(local_commit),
            remote_reference,
            CommitHash(remote_commit),
        )
