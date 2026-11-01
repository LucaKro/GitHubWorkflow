"""
The environment variables this package sets or reads, grouped by who reads them.
"""

from __future__ import annotations

from basstler_domain_model.environment import EnvironmentVariable

# %% this workflow


class WorkflowVariable(EnvironmentVariable):
    """
    The variables the workflow's hooks read.
    """

    PYTHON = "GITHUB_WORKFLOW_PYTHON"
    """
    The interpreter the package is installed in, for the hooks to run it with.
    """


# %% git, run without a person at the keyboard


class GitBatchVariable(EnvironmentVariable):
    """
    The variables that keep git from asking for credentials when nobody can answer.
    """

    TERMINAL_PROMPT = "GIT_TERMINAL_PROMPT"
    """
    Whether git may prompt on the terminal; ``0`` makes it fail instead.
    """

    SSH_COMMAND = "GIT_SSH_COMMAND"
    """
    The ssh command git runs, here one that fails instead of asking.
    """
