"""
A branch used to store files: read from its remote-tracking reference, written by
commits built without a checkout, and pushed without force.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from domain_model.git.commands import GitCommandResult
from domain_model.git.exceptions import (
    StorageBranchPushRefused,
    StorageBranchWriteConflict,
)
from domain_model.git.remotes import ProposedPush, RemoteBranch
from domain_model.git.revisions import Commit, TextFiles

# %% the branch


@dataclass(frozen=True)
class StorageBranch:
    """
    A branch on a remote that holds files rather than a project's history, so the
    checkout it is used from is never touched.
    """

    branch: RemoteBranch
    """
    The branch, read from its remote-tracking branch so neither a local branch nor
    ``FETCH_HEAD`` moves; its remote runs git in the checkout it is used from.
    """

    def fetch(self) -> bool:
        """
        Bring the remote-tracking reference to the branch's tip on the remote.

        :return: Whether the branch exists on the remote.
        :raises GitCommandFailed: If the remote cannot be reached.
        """
        tip = self.branch.tip()
        tracking = self.branch.tracking_branch
        if tip is None:
            tracking.delete()
            return False
        fetched = tracking.commit_or_none()
        if fetched is None or fetched.hash != tip:
            self.branch.fetch().raise_if_failed()
        return True

    def read(self, path: Path) -> str | None:
        """
        :param path: A file on the branch.
        :return: Its content as last fetched, ``None`` when it does not exist.
        """
        return self.branch.tracking_branch.file_text(path)

    def write(self, files: TextFiles, message: str) -> None:
        """
        Commit *files* on top of the branch's tip and push the commit.

        When another writer pushed first, the commit is built again on the new tip;
        writers that write different files never need a merge.

        :param files: The text of each file to write.
        :param message: The commit message.
        :raises StorageBranchWriteConflict: If another writer pushed first and changed
            one of *files*.
        :raises StorageBranchPushRefused: If the push is refused twice.
        """
        base = self.branch.tracking_branch.commit_or_none()
        pushed = self._push(files, message)
        if not pushed.succeeded:
            self.fetch()
            self._refuse_overwriting(base, files)
            pushed = self._push(files, message)
        if not pushed.succeeded:
            raise StorageBranchPushRefused(self.branch, pushed.error_output)
        self.fetch()

    def _refuse_overwriting(self, base: Commit | None, files: TextFiles) -> None:
        """
        :param base: The tip the write was first built on, ``None`` when the branch did
            not exist.
        :param files: The files the write changes.
        :raises StorageBranchWriteConflict: If any of *files* differs between *base* and
            the fetched tip.
        """
        tip = self.branch.tracking_branch.commit_or_none()
        changed = tuple(
            path
            for path in files.paths
            if (base and base.file_blob(path)) != (tip and tip.file_blob(path))
        )
        if changed:
            raise StorageBranchWriteConflict(self.branch, changed)

    def _push(self, files: TextFiles, message: str) -> GitCommandResult:
        """
        :param files: The text of each file to write.
        :param message: The commit message.
        :return: The finished push of a commit holding *files* on the fetched tip.
        """
        tip = self.branch.tracking_branch.commit_or_none()
        commit = (
            Commit.write_root(self.branch.remote.git, files, message)
            if tip is None
            else tip.write_child(files, message)
        )
        return ProposedPush(self.branch, commit).publish()
