"""
The architecture diagrams of projects drawn into their READMEs, as each project's
``pyproject.toml`` declares them under ``[tool.architecture-diagrams]``; any installed
project can be drawn.

Usage: ``python -m github_workflow.architecture [--check] [project ...]``, the current
directory when no project is given; with ``--check`` nothing is written, and it exits
with :attr:`DrawingStatus.OUTDATED` when a README no longer matches its source.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from pathlib import Path

from domain_model.architecture.readme import ArchitectureReadme

# %% the command line


class DrawingArgument(StrEnum):
    """
    The arguments the command takes.
    """

    CHECK = "--check"
    """
    Report outdated READMEs instead of drawing them.
    """

    PROJECTS = "projects"
    """
    The roots of the projects to draw.
    """


class DrawingStatus(IntEnum):
    """
    The statuses the command exits with.
    """

    CURRENT = 0
    """
    Every README holds, or now holds, the diagrams its source draws.
    """

    OUTDATED = 1
    """
    A README checked no longer matches its source.
    """


# %% drawing


@dataclass(frozen=True)
class ArchitectureDrawing:
    """
    The READMEs of some projects, drawn anew or checked.
    """

    projects: list[Path]
    """
    The roots of the projects.
    """

    check_only: bool
    """
    Whether to report outdated READMEs instead of drawing them.
    """

    def run(self) -> DrawingStatus:
        """
        :return: Whether every README is current, once drawn when not only checked.
        """
        readmes = [ArchitectureReadme.from_project(root) for root in self.projects]
        if not self.check_only:
            for readme in readmes:
                readme.write()
            return DrawingStatus.CURRENT
        outdated = [readme.path for readme in readmes if not readme.is_current()]
        for path in outdated:
            print(f"{path} no longer matches its source; draw it anew", file=sys.stderr)
        return DrawingStatus.OUTDATED if outdated else DrawingStatus.CURRENT


def main() -> None:
    """
    Draw or check the READMEs of the projects the command line names.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(DrawingArgument.CHECK, action="store_true")
    parser.add_argument(DrawingArgument.PROJECTS, nargs="*", type=Path)
    arguments = parser.parse_args()
    drawing = ArchitectureDrawing(
        projects=arguments.projects or [Path.cwd()], check_only=arguments.check
    )
    sys.exit(drawing.run())


if __name__ == "__main__":
    main()
