"""
The checkout a session works in.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from basstler_domain_model.git.commands import GitCommandRunner

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
        :raises GitCommandFailed: If *directory* is not inside a git checkout.
        """
        root = GitCommandRunner(directory).run("rev-parse", "--show-toplevel")
        return cls(GitCommandRunner(Path(root)))

    @property
    def root(self) -> Path:
        """:return: The checkout's top directory."""
        return self.git.working_directory

    @property
    def branch(self) -> str:
        """:return: The checked-out branch, empty on a detached ``HEAD``."""
        return self.git.run("branch", "--show-current")

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
