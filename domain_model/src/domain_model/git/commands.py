"""
Running git in one checkout, reporting failures rather than swallowing them.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from domain_model.class_property import classproperty
from domain_model.commands import CommandResult, CommandRunner
from domain_model.environment import GitVariable
from domain_model.git.exceptions import GitCommandFailed
from domain_model.git.options import CloneOption, GitGlobalOption, RevParseOption
from domain_model.git.subcommands import GitSubcommand
from domain_model.programs import Program

# %% who a commit records


class GitIdentity(StrEnum):
    """
    The identities a commit records, as ``git var`` names them.
    """

    AUTHOR = "GIT_AUTHOR_IDENT"
    """
    Who wrote the change.
    """

    COMMITTER = "GIT_COMMITTER_IDENT"
    """
    Who recorded the commit.
    """


# %% running git


@dataclass(frozen=True)
class GitCommandResult(CommandResult):
    """
    One finished git command, whether or not it succeeded.
    """

    @classmethod
    def from_command_result(cls, result: CommandResult) -> GitCommandResult:
        """
        :param result: A finished ``git`` command.
        :return: It, as a git command.
        """
        return cls(
            result.arguments,
            result.exit_status,
            result.standard_output,
            result.error_output,
            result.seconds,
        )

    def raise_if_failed(self) -> GitCommandResult:
        """:return: This result, when the command succeeded.
        :raises GitCommandFailed: When it did not."""
        if not self.succeeded:
            raise GitCommandFailed(
                status=self.exit_status,
                detail=self.error_output,
                arguments=self.arguments,
            )
        return self


@dataclass(frozen=True)
class GitCommandRunner:
    """
    Runs git in one checkout, reporting failures rather than swallowing them.
    """

    working_directory: Path
    """
    The checkout every command runs in.
    """

    @classproperty
    def unattended_environment(cls) -> dict[str, str]:
        """
        The variables every git command runs with, so it fails rather than waits for a
        person.
        """
        return {GitVariable.TERMINAL_PROMPT: "0"}

    @classmethod
    def clone(cls, url: str, destination: Path) -> GitCommandRunner:
        """
        Clone a repository into a new checkout.

        :param url: The repository to clone, as git fetches it.
        :param destination: The new checkout's directory, absent or empty.
        :return: Runs git in the new checkout.
        :raises GitCommandFailed: If the repository cannot be cloned there.
        """
        checkout = destination.absolute()
        checkout.parent.mkdir(parents=True, exist_ok=True)
        cls(checkout.parent).run(
            GitSubcommand.CLONE, CloneOption.QUIET, url, str(checkout)
        )
        return cls(checkout)

    @classmethod
    def from_enclosed_directory(cls, directory: Path) -> GitCommandRunner | None:
        """
        :param directory: A directory.
        :return: Runs git at the root of the checkout the directory is inside, ``None``
            when it is inside none.
        """
        root = cls(directory).attempt(
            GitSubcommand.REV_PARSE, RevParseOption.SHOW_TOPLEVEL
        )
        return cls(Path(root.output)) if root.succeeded else None

    def attempt(
        self, *arguments: str, environment: Mapping[str, str] | None = None
    ) -> GitCommandResult:
        """
        Run a command whose failure is an expected outcome, failing rather than
        prompting on the terminal.

        :param arguments: The git subcommand and its arguments.
        :param environment: Variables to set for this command on top of the process's
            own.
        :return: The finished command.
        """
        return GitCommandResult.from_command_result(
            CommandRunner(self.working_directory).run(
                Program.GIT,
                *arguments,
                environment={**self.unattended_environment, **(environment or {})},
            )
        )

    def run(self, *arguments: str, environment: Mapping[str, str] | None = None) -> str:
        """
        Run a command the caller depends on the result of.

        :param arguments: The git subcommand and its arguments.
        :param environment: Variables to set for this command on top of the process's
            own.
        :return: Git's stripped stdout.
        :raises GitCommandFailed: If git exits non-zero.
        """
        return (
            self.attempt(*arguments, environment=environment).raise_if_failed().output
        )

    def repository_state_path(self, location: Path) -> Path:
        """
        :param location: Scratch state kept per repository.
        :return: Where it lives for this checkout's repository, the same from every
            worktree of it.
        """
        common_directory = self.run(
            GitSubcommand.REV_PARSE,
            RevParseOption.ABSOLUTE_PATHS,
            RevParseOption.COMMON_DIRECTORY,
        )
        return Path(common_directory) / location

    def git_path(self, location: Path) -> Path:
        """
        :param location: A file inside the git directory, relative to it.
        :return: Where it is for this checkout, which may differ between worktrees.
        """
        return self.working_directory / self.run(
            GitSubcommand.REV_PARSE, RevParseOption.GIT_PATH, str(location)
        )

    def version(self) -> str:
        """:return: Git's version, as ``git --version`` prints it."""
        return self.run(GitGlobalOption.VERSION)

    def identity(self, identity: GitIdentity) -> str:
        """
        :param identity: Which of the identities a commit records.
        :return: It, as a commit made now would record it: ``Name <address>`` followed
            by the time.
        """
        return self.run(GitSubcommand.VAR, identity)
