"""
The errors drawing a package's architecture or writing it into a README ends in.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from domain_model.exceptions import DataclassException

# %% drawing


@dataclass
class ClassNameCollisionError(DataclassException, ValueError):
    """
    Raised when two classes one class diagram shows share a name, which the diagram
    could not tell apart.
    """

    diagram: str
    """
    The key of the diagram.
    """

    qualified_names: list[str]
    """
    The import paths of the classes sharing the name.
    """

    def error_message(self) -> str:
        return f"diagram {self.diagram!r} shows {' and '.join(self.qualified_names)}"

    def suggest_correction(self) -> str:
        return "Show the modules defining them in separate class diagrams"


# %% writing the README


@dataclass
class MissingDiagramMarkerError(DataclassException, LookupError):
    """
    Raised when a README lacks the comments marking where one of its diagrams goes.
    """

    readme: Path
    """
    The README.
    """

    marker: str
    """
    The comment it lacks.
    """

    def error_message(self) -> str:
        return f"{self.readme} has no {self.marker!r}"

    def suggest_correction(self) -> str:
        return "Add the comments opening and closing the diagram where it goes"
