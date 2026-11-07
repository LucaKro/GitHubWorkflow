"""
Finding the GitHub token a client calls the API with.
"""

from __future__ import annotations

from dataclasses import dataclass

from basstler_domain_model.commands import CommandRunner
from basstler_domain_model.environment import GitHubCredentialVariable
from basstler_domain_model.github.exceptions import GitHubCredentialUnavailableError
from basstler_domain_model.github.vocabulary import GitHubClient

# %% the token


@dataclass(frozen=True)
class GitHubToken:
    """
    The token from the environment, as a cloud session and GitHub Actions set it, or
    else the one ``gh`` is logged in with, as a local machine usually has it.
    """

    runner: CommandRunner
    """
    Runs ``gh`` when the environment names no token.
    """

    def find(self) -> str:
        """
        :return: The token.
        :raises GitHubCredentialUnavailableError: If neither the environment nor ``gh``
            has one.
        """
        token = GitHubCredentialVariable.first_token()
        if token:
            return token
        logged_in = self.runner.run(GitHubClient.COMMAND_LINE, "auth", "token")
        if not logged_in.succeeded or not logged_in.output:
            raise GitHubCredentialUnavailableError(tuple(GitHubCredentialVariable))
        return logged_in.output
