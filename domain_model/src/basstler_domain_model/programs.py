"""
The programs that reach git or GitHub.
"""

from __future__ import annotations

import re
from enum import StrEnum

# %% programs


class Program(StrEnum):
    """
    The programs the guard judges, by their executable's name.
    """

    GIT = "git"
    """
    Git itself.
    """

    GITHUB_CLI = "gh"
    """
    GitHub's command-line client.
    """

    CURL = "curl"
    """
    An HTTP client that could call GitHub's API.
    """

    WGET = "wget"
    """
    Another HTTP client that could call GitHub's API.
    """

    @classmethod
    def any_named(cls, command_line: str) -> bool:
        """
        :param command_line: A Bash command line.
        :return: Whether it names any of the programs as a word of its own.
        """
        names = "|".join(re.escape(program) for program in cls)
        return re.search(rf"\b({names})\b", command_line) is not None
