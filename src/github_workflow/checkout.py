"""
The checkout a session works in.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from basstler_domain_model.git.commands import GitCommandRunner

from github_workflow.exceptions import NotACheckoutError
from github_workflow.locations import GitFile, ProjectFile

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
        root = GitCommandRunner(directory).attempt("rev-parse", "--show-toplevel")
        return cls(GitCommandRunner(Path(root.output))) if root.succeeded else None

    @property
    def root(self) -> Path:
        """:return: The checkout's top directory."""
        return self.git.working_directory

    @property
    def claude_local(self) -> Path:
        """:return: Where ``CLAUDE.local.md`` lives in this checkout."""
        return self.root / ProjectFile.CLAUDE_LOCAL

    def exclude_claude_local(self) -> None:
        """
        Add ``CLAUDE.local.md`` to the repository's own ignore list, once, so it is
        never committed and no file of the project changes.
        """
        exclude = self.root / self.git.run(
            "rev-parse", "--git-path", str(GitFile.EXCLUDE)
        )
        lines = exclude.read_text().splitlines() if exclude.exists() else []
        if str(ProjectFile.CLAUDE_LOCAL) in lines:
            return
        exclude.parent.mkdir(parents=True, exist_ok=True)
        exclude.write_text("\n".join([*lines, str(ProjectFile.CLAUDE_LOCAL)]) + "\n")
