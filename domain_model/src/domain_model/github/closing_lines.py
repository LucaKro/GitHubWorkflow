"""
The lines of a pull request's description that close an issue once it is merged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from domain_model.github.vocabulary import ClosingKeyword

# %% closing lines


@dataclass(frozen=True)
class ClosingLines:
    """
    The lines of a pull request's description that close an issue once it is merged,
    such as ``Fixes #148``.
    """

    description: str
    """
    The description.
    """

    def lines(self) -> list[str]:
        """
        :return: The closing lines, in order.
        """
        keyword = "|".join(map(re.escape, ClosingKeyword))
        closing = re.compile(rf"(?:{keyword}) #\d+")
        stripped = (line.strip() for line in self.description.splitlines())
        return [line for line in stripped if closing.fullmatch(line)]

    def issues(self) -> list[int]:
        """
        :return: The issues of the description's repository that the closing lines
            close, in order.
        """
        return [int(line.rpartition("#")[2]) for line in self.lines()]

    def append_missing_lines(self, rewritten: str) -> str:
        """
        :param rewritten: A new description replacing this one.
        :return: It, ending with every closing line of this one it lacks.
        """
        held = ClosingLines(rewritten).lines()
        missing = [line for line in self.lines() if line not in held]
        if not missing:
            return rewritten
        return f"{rewritten.rstrip()}\n\n" + "\n".join(missing) + "\n"
