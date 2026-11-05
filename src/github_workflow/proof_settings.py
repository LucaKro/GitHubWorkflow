"""
How a project's proofs run, as its ``pyproject.toml`` says.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from github_workflow.locations import ProjectFile

# %% how a project's proofs run


class ProofSettingKey(StrEnum):
    """
    The keys leading to, and inside, the table of a project's ``pyproject.toml`` saying
    how its proofs run: ``[tool.github-workflow.proofs]``.
    """

    TOOL = "tool"
    """
    The table every tool's settings are in.
    """

    WORKFLOW = "github-workflow"
    """
    The workflow's table in it.
    """

    PROOFS = "proofs"
    """
    The proofs' table in that.
    """

    PYTEST_OPTIONS = "pytest-options"
    """
    The options pytest is run with, one argument each.
    """

    SETUP = "setup"
    """
    The command lines run first, each by the project's interpreter.
    """


@dataclass(frozen=True)
class ProofSettings:
    """
    How a project's proofs run.
    """

    pytest_options: tuple[str, ...] = ()
    """
    The options pytest is run with, on top of the workflow's own, one argument each.
    """

    setup: tuple[str, ...] = ()
    """
    The command lines the project's interpreter runs in the default branch's files
    before the test, in order, each giving its arguments, such as a script generating
    files git ignores.
    """

    @classmethod
    def read(cls, project: Path) -> ProofSettings:
        """
        :param project: The project's root.
        :return: What its ``pyproject.toml`` says, nothing when it has none.
        """
        file = project / ProjectFile.PYPROJECT
        if not file.exists():
            return cls()
        return cls.from_pyproject(tomllib.loads(file.read_text()))

    @classmethod
    def from_pyproject(cls, data: dict[str, Any]) -> ProofSettings:
        """
        :param data: A ``pyproject.toml``.
        :return: What its table on proofs says.
        """
        tool = data.get(ProofSettingKey.TOOL, {})
        table = tool.get(ProofSettingKey.WORKFLOW, {}).get(ProofSettingKey.PROOFS, {})
        return cls(
            tuple(table.get(ProofSettingKey.PYTEST_OPTIONS, ())),
            tuple(table.get(ProofSettingKey.SETUP, ())),
        )
