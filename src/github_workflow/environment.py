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
