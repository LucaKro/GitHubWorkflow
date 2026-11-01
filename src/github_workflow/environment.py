"""
The environment variables this package sets or reads, grouped by who reads them.
"""

from __future__ import annotations

from basstler_domain_model.environment import EnvironmentVariable

# %% git


class GitVariable(EnvironmentVariable):
    """
    The variables git reads, which a command sets to steer it.
    """

    INDEX_FILE = "GIT_INDEX_FILE"
    """
    The index git builds a tree in, set to keep the checkout's own index untouched.
    """
