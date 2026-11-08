"""
The environment variables the workflow's hooks and commands set or read.
"""

from __future__ import annotations

from basstler_domain_model.environment import EnvironmentVariable

# %% this workflow


class WorkflowVariable(EnvironmentVariable):
    """
    The variables the workflow's hooks set or read.
    """

    PYTHON = "GITHUB_WORKFLOW_PYTHON"
    """
    The interpreter the package is installed in, for the hooks to run it with.
    """

    INSTALLED = "GITHUB_WORKFLOW_INSTALLED"
    """
    What the session start's hook installed before the session began, empty when
    nothing.
    """

    PLUGIN_ROOT = "GITHUB_WORKFLOW_PLUGIN_ROOT"
    """
    Where the plugin is, set for the session's commands.
    """

    PLUGIN_DATA = "GITHUB_WORKFLOW_PLUGIN_DATA"
    """
    The directory Claude Code keeps the plugin's data in, set for the session's
    commands.
    """
