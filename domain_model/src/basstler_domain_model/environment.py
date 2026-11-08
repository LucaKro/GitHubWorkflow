"""
The environment variables this package reads, grouped by who sets them.

Every group is an :class:`EnvironmentVariable`, so reading one is the same call
whichever group it belongs to, and a variable is named once rather than typed out where
it is read.
"""

from __future__ import annotations

import os
from enum import StrEnum

# %% the base every group extends


class EnvironmentVariable(StrEnum):
    """
    An environment variable, named by its value.

    The base every group of them extends.
    """

    def read(self) -> str | None:
        """
        :return: The variable's value in this process's environment, or ``None`` when it
            is not set.
        """
        return os.environ.get(self)


# %% GitHub


class GitHubCredentialVariable(EnvironmentVariable):
    """
    The variables a GitHub token is read from, in the order they are tried.
    """

    GH_TOKEN = "GH_TOKEN"
    """
    The token the ``gh`` CLI reads, preferred where both are set.
    """

    GITHUB_TOKEN = "GITHUB_TOKEN"
    """
    The token GitHub Actions hands a workflow.
    """

    @classmethod
    def first_token(cls) -> str | None:
        """
        :return: The first non-empty token, in the order the variables are tried, or
            ``None`` when none is set.
        """
        return next((token for variable in cls if (token := variable.read())), None)


class GitHubActionsVariable(EnvironmentVariable):
    """
    The variables a GitHub Actions runner sets for the steps it runs.
    """

    STEP_SUMMARY = "GITHUB_STEP_SUMMARY"
    """
    The file a step appends its Markdown job summary to.
    """

    OUTPUT = "GITHUB_OUTPUT"
    """
    The file a step appends its ``<key>=<value>`` outputs to.
    """

    RUNNER_TEMPORARY_DIRECTORY = "RUNNER_TEMP"
    """
    A directory the runner empties for each job, which steps hand files through.
    """

    REPOSITORY_OWNER = "GITHUB_REPOSITORY_OWNER"
    """
    The owner of the repository the workflow runs in.
    """

    API_URL = "GITHUB_API_URL"
    """
    Where the runner's GitHub answers its REST API.
    """


# %% Claude Code


class ClaudeCodeVariable(EnvironmentVariable):
    """
    The environment variables Claude Code sets for the commands it runs.
    """

    PROJECT_DIRECTORY = "CLAUDE_PROJECT_DIR"
    """
    The root of the project the session runs in.
    """

    REMOTE = "CLAUDE_CODE_REMOTE"
    """
    ``true`` in a Claude Code cloud session, whose proxy answers GitHub's REST API but
    not its GraphQL API.
    """

    SESSION_IDENTIFIER = "CLAUDE_CODE_SESSION_ID"
    """
    The session's own identifier, which names its transcript file.
    """

    CONFIGURATION_DIRECTORY = "CLAUDE_CONFIG_DIR"
    """
    Where Claude Code keeps its state, transcripts included, when not ``~/.claude``.
    """

    GIT_BASH_PATH = "CLAUDE_CODE_GIT_BASH_PATH"
    """
    The bash Claude Code runs its commands in on Windows, when set.
    """

    COMMAND_MARKER = "CLAUDECODE"
    """
    ``1`` in every command Claude Code runs, and unset in a person's own terminal.
    """


# %% git


class GitVariable(EnvironmentVariable):
    """
    The variables git reads, which a command sets to steer it.
    """

    INDEX_FILE = "GIT_INDEX_FILE"
    """
    The index git builds a tree in, set to keep the checkout's own index untouched.
    """

    TERMINAL_PROMPT = "GIT_TERMINAL_PROMPT"
    """
    Whether git may prompt on the terminal for a credential, ``0`` to make it fail
    instead.
    """


class GitIdentityVariable(EnvironmentVariable):
    """
    The variables git takes a commit's author and committer from, ahead of its
    configured ``user.name`` and ``user.email``.
    """

    AUTHOR_NAME = "GIT_AUTHOR_NAME"
    """
    The name a commit is authored under.
    """

    AUTHOR_EMAIL = "GIT_AUTHOR_EMAIL"
    """
    The address a commit is authored under.
    """

    COMMITTER_NAME = "GIT_COMMITTER_NAME"
    """
    The name a commit is committed under.
    """

    COMMITTER_EMAIL = "GIT_COMMITTER_EMAIL"
    """
    The address a commit is committed under.
    """


# %% Python


class PythonVariable(EnvironmentVariable):
    """
    The variables the Python interpreter reads when it starts.
    """

    MODULE_SEARCH_PATH = "PYTHONPATH"
    """
    Directories searched for modules before the installed packages.
    """
