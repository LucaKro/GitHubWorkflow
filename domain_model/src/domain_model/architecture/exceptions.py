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


# %% reading a project's settings


@dataclass
class MissingArchitectureSettingsError(DataclassException, LookupError):
    """
    Raised when a project's ``pyproject.toml`` declares no architecture diagrams.
    """

    project: Path
    """
    The project's root.
    """

    def error_message(self) -> str:
        return f"{self.project} declares no [tool.architecture-diagrams]"

    def suggest_correction(self) -> str:
        return (
            "Declare the README, the package and its diagrams under "
            "[tool.architecture-diagrams] in the project's pyproject.toml"
        )


@dataclass
class UnknownGroupError(DataclassException, LookupError):
    """
    Raised when a diagram names a group of modules the project's settings do not
    declare.
    """

    title: str
    """
    The group's title, as the diagram names it.
    """

    declared_titles: list[str]
    """
    The titles of the groups the settings declare.
    """

    def error_message(self) -> str:
        return f"no group is titled {self.title!r}"

    def suggest_correction(self) -> str:
        return f"Name one of {', '.join(self.declared_titles) or 'no groups yet'}"


@dataclass
class UnknownModuleError(DataclassException, LookupError):
    """
    Raised when a diagram names a module or package the drawn package lacks, as after
    the module was renamed.
    """

    diagram: str
    """
    The key of the diagram.
    """

    module_name: str
    """
    The import path it names.
    """

    def error_message(self) -> str:
        return (
            f"diagram {self.diagram!r} names {self.module_name}, which does not exist"
        )

    def suggest_correction(self) -> str:
        return "Name the module by its current import path in the project's settings"
