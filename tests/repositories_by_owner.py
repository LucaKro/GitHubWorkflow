"""
Bare repositories laid out as ``<root>/<owner>/<name>.git``, so a ``file://`` URL names an
owner the way a GitHub URL does, and clones of them.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from domain_model.class_property import classproperty
from domain_model.git.commands import GitCommandRunner
from domain_model.git.revisions import BranchName

from github_workflow.checkout import ProjectCheckout

# %% the layout


@dataclass(frozen=True)
class RepositoriesByOwner:
    """
    Scratch repositories grouped by the account that owns them.
    """

    root: Path
    """
    The directory holding every owner's repositories and every clone.
    """

    @classproperty
    def foreign_owner(cls) -> str:
        """
        An account that is not the workflow's owner.
        """
        return "someone-else"

    @classproperty
    def default_branch(cls) -> BranchName:
        """
        The branch every repository starts with.
        """
        return BranchName("main")

    @classproperty
    def repository_name(cls) -> str:
        """
        The name every repository is created under unless given another.
        """
        return "project"

    def create(self, owner: str, name: str | None = None) -> str:
        """
        :param owner: The account the repository belongs to.
        :param name: The repository's name.
        :return: The URL of a new bare repository holding one commit.
        """
        name = name or self.repository_name
        bare = self.root / owner / f"{name}.git"
        GitCommandRunner(self.root).run(
            "init",
            "--quiet",
            "--bare",
            f"--initial-branch={self.default_branch}",
            str(bare),
        )
        seed = self.root / "seeds" / owner / name
        seed.mkdir(parents=True)
        git = GitCommandRunner(seed)
        git.run("init", "--quiet", f"--initial-branch={self.default_branch}")
        self.identify(git)
        git.run("commit", "--quiet", "--allow-empty", "--message", "Start")
        git.run("push", "--quiet", str(bare), f"HEAD:refs/heads/{self.default_branch}")
        return f"file://{bare}"

    def clone(self, url: str, directory: str) -> ProjectCheckout:
        """
        :param url: The repository to clone.
        :param directory: The clone's directory name under the root.
        :return: The clone, with an identity to commit as.
        """
        destination = self.root / "clones" / directory
        GitCommandRunner(self.root).run("clone", "--quiet", url, str(destination))
        checkout = ProjectCheckout.containing(destination)
        self.identify(checkout.git)
        return checkout

    @staticmethod
    def identify(git: GitCommandRunner) -> None:
        """
        :param git: A checkout to commit in.
        """
        git.run("config", "user.name", "Test Author")
        git.run("config", "user.email", "test.author@example.com")

    def branches(self, url: str) -> str:
        """
        :param url: A repository.
        :return: Every branch it holds, as ``git ls-remote`` lists them.
        """
        return GitCommandRunner(self.root).run("ls-remote", "--heads", url)

    @staticmethod
    def is_ancestor(git: GitCommandRunner, candidate: str, descendant: str) -> bool:
        """
        :param git: A checkout.
        :param candidate: Anything git resolves to a commit.
        :param descendant: Another.
        :return: Whether *candidate* is in *descendant*'s history, as git answers.
        """
        return git.attempt(
            "merge-base", "--is-ancestor", candidate, descendant
        ).succeeded
