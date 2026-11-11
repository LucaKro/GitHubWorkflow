"""
The checkout a session works in.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from domain_model.git.commands import GitCommandRunner
from domain_model.git.working_tree import Merge, WorkingTree
from domain_model.locations import GitStateFile

from github_workflow.exceptions import NotACheckoutError
from github_workflow.locations import ProjectFile

# %% the checkout


@dataclass(frozen=True)
class ProjectCheckout:
    """
    A git checkout, addressed from its root.
    """

    git: GitCommandRunner
    """
    Runs git at the checkout's root.
    """

    @classmethod
    def containing(cls, directory: Path) -> ProjectCheckout:
        """
        :param directory: Any directory inside the checkout.
        :return: The checkout.
        :raises NotACheckoutError: If *directory* is not inside a git checkout.
        """
        checkout = cls.around(directory)
        if checkout is None:
            raise NotACheckoutError(str(directory))
        return checkout

    @classmethod
    def around(cls, directory: Path) -> ProjectCheckout | None:
        """
        :param directory: A directory.
        :return: The checkout it is inside, ``None`` when it is inside none.
        """
        git = GitCommandRunner.enclosing(directory)
        return None if git is None else cls(git)

    @cached_property
    def working_tree(self) -> WorkingTree:
        """
        The files checked out, and the branch they are on.
        """
        return WorkingTree(self.git)

    @cached_property
    def merge(self) -> Merge:
        """
        A merge into the checked-out branch, in progress or not.
        """
        return Merge(self.working_tree)

    @property
    def checked_out_branch_name(self) -> str:
        """:return: The checked-out branch's name, empty on a detached ``HEAD``."""
        branch = self.working_tree.checked_out_branch()
        return "" if branch is None else branch.name

    @property
    def root(self) -> Path:
        """:return: The checkout's top directory."""
        return self.git.working_directory

    @property
    def claude_local(self) -> Path:
        """:return: Where ``CLAUDE.local.md`` lives in this checkout."""
        return self.root / ProjectFile.CLAUDE_LOCAL

    @property
    def claude_local_text(self) -> str:
        """:return: ``CLAUDE.local.md``'s text, empty when it does not exist."""
        local = self.claude_local
        return local.read_text() if local.exists() else ""

    def exclude_claude_local(self) -> None:
        """
        Add ``CLAUDE.local.md`` to the repository's own ignore list, once, so it is
        never committed and no file of the project changes.
        """
        exclude = self.git.git_path(GitStateFile.EXCLUDE)
        lines = exclude.read_text().splitlines() if exclude.exists() else []
        if str(ProjectFile.CLAUDE_LOCAL) in lines:
            return
        exclude.parent.mkdir(parents=True, exist_ok=True)
        exclude.write_text("\n".join([*lines, str(ProjectFile.CLAUDE_LOCAL)]) + "\n")
