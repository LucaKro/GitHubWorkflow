"""
Reading and writing the notes branch without checking it out.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from basstler_domain_model.git.commands import GitCommandRunner

from github_workflow.environment import GitVariable
from github_workflow.exceptions import NotesSaveRefusedError
from github_workflow.remotes import OwnedRemote
from github_workflow.settings import WorkflowSettings

# %% the branch


@dataclass(frozen=True)
class NotesBranch:
    """
    The notes branch on the owner's remote, read from a private reference and written by
    building commits in an index of their own, so the checkout is never touched.
    """

    git: GitCommandRunner
    """
    Runs git in the checkout.
    """

    remote: OwnedRemote
    """
    The remote the branch lives on.
    """

    settings: WorkflowSettings
    """
    The branch's name, and where a fetch of it is kept.
    """

    def fetch(self) -> bool:
        """
        Bring the private reference to the branch's tip on the remote.

        :return: Whether the branch exists on the remote.
        :raises GitCommandFailed: If the remote cannot be reached.
        """
        listed = self.git.run(
            "ls-remote", "--heads", self.remote.name, self.settings.notes_branch
        )
        if not listed:
            self.git.attempt("update-ref", "-d", self.settings.notes_reference)
            return False
        self.git.run(
            "fetch",
            "--quiet",
            "--no-write-fetch-head",
            self.remote.name,
            f"+refs/heads/{self.settings.notes_branch}:{self.settings.notes_reference}",
        )
        return True

    def read(self, path: Path) -> str | None:
        """
        :param path: A file on the branch.
        :return: Its content as last fetched, ``None`` when it does not exist.
        """
        shown = self.git.attempt("show", f"{self.settings.notes_reference}:{path}")
        return shown.output if shown.succeeded else None

    def write(self, contents: dict[Path, str], message: str) -> None:
        """
        Commit *contents* on top of the branch's tip and push the commit.

        When another session pushed first, the commit is built again on the new tip;
        every session only writes its own files, so that never needs a merge.

        :param contents: The text of each file to write.
        :param message: The commit message.
        :raises NotesSaveRefusedError: If the push is refused twice.
        """
        pushed = self.git.attempt(
            *self._push_arguments(self._commit(contents, message))
        )
        if not pushed.succeeded:
            self.fetch()
            pushed = self.git.attempt(
                *self._push_arguments(self._commit(contents, message))
            )
        if not pushed.succeeded:
            raise NotesSaveRefusedError(self.settings.notes_branch, pushed.error_output)
        self.fetch()

    def _push_arguments(self, commit: str) -> tuple[str, ...]:
        """
        :param commit: The commit to publish.
        :return: The push publishing it as the branch, never forced.
        """
        return (
            "push",
            "--quiet",
            self.remote.name,
            f"{commit}:refs/heads/{self.settings.notes_branch}",
        )

    def _commit(self, contents: dict[Path, str], message: str) -> str:
        """
        :param contents: The text of each file to write.
        :param message: The commit message.
        :return: A commit holding the fetched tip's files with *contents* written over
            them, whose parent is that tip, or which has none when the branch does not
            exist yet.
        """
        parent = self.git.commit_or_none(self.settings.notes_reference)
        with tempfile.TemporaryDirectory() as directory:
            index = {GitVariable.INDEX_FILE: str(Path(directory) / "index")}
            if parent is not None:
                self.git.run("read-tree", parent, environment=index)
            for path, text in contents.items():
                staged = Path(directory) / "content"
                staged.write_text(text)
                blob = self.git.run("hash-object", "-w", str(staged))
                self.git.run(
                    "update-index",
                    "--add",
                    "--cacheinfo",
                    f"100644,{blob},{path}",
                    environment=index,
                )
            tree = self.git.run("write-tree", environment=index)
        parents = () if parent is None else ("-p", parent)
        return self.git.run("commit-tree", tree, *parents, "-m", message)
