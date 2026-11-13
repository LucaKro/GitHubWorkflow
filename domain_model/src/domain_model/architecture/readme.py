"""
A README holding diagrams of a package's architecture, each between two comments, kept
equal to what the package's current source draws.
"""

from __future__ import annotations

import pkgutil
from dataclasses import dataclass
from enum import Enum, StrEnum
from pathlib import Path

from domain_model.architecture.diagrams import Diagram, ModuleGroups
from domain_model.architecture.exceptions import (
    MissingArchitectureSettingsError,
    MissingDiagramMarkerError,
    UnknownModuleError,
)
from domain_model.architecture.keys import ArchitectureKey, DiagramKind
from domain_model.architecture.source import PythonPackage
from domain_model.class_property import classproperty
from domain_model.markdown import CodeFence, CommentDelimiter
from domain_model.python_project import Pyproject

# %% where a diagram goes


class DiagramMarker(StrEnum):
    """
    The comments a README marks a diagram's place with, each naming the diagram.
    """

    START = "diagram"
    """
    The comment before the diagram.
    """

    END = "end of diagram"
    """
    The comment after it.
    """

    def comment(self, key: str) -> str:
        """
        :param key: The key of the diagram.
        :return: The comment marking it.
        """
        return f"{CommentDelimiter.OPEN}{self}: {key}{CommentDelimiter.CLOSE}"


# %% the README


@dataclass(frozen=True)
class ArchitectureReadme:
    """
    A package's README, whose diagrams are drawn from the package's source and whose
    every other line is written by hand.
    """

    path: Path
    """
    The README.
    """

    package: PythonPackage
    """
    The package its diagrams draw.
    """

    diagrams: tuple[Diagram, ...]
    """
    The diagrams it holds.
    """

    def __post_init__(self) -> None:
        """
        :raises UnknownModuleError: If a diagram names a module the package lacks.
        """
        for diagram in self.diagrams:
            for module_name in sorted(diagram.module_names()):
                if module_name not in self.package.modules:
                    raise UnknownModuleError(diagram.key, module_name)

    @classproperty
    def default_left_out_bases(cls) -> tuple[type, ...]:
        """
        The classes class diagrams leave out when a project's settings name none:

        enumerations and errors.
        """
        return Enum, BaseException

    @classmethod
    def from_project(cls, root: Path) -> ArchitectureReadme:
        """
        :param root: A project's root, whose ``pyproject.toml`` declares its README's
            diagrams under ``[tool.architecture-diagrams]``.
        :return: The project's README.
        :raises MissingArchitectureSettingsError: If the project declares no diagrams.
        :raises UnknownGroupError: If a diagram names a group the settings lack.
        :raises UnknownModuleError: If a diagram names a module the package lacks.
        """
        tools = Pyproject(root).settings().get(ArchitectureKey.TOOL, {})
        if ArchitectureKey.TABLE not in tools:
            raise MissingArchitectureSettingsError(root)
        settings = tools[ArchitectureKey.TABLE]
        left_out_names = settings.get(ArchitectureKey.LEFT_OUT_BASES)
        left_out_bases = (
            cls.default_left_out_bases
            if left_out_names is None
            else tuple(map(pkgutil.resolve_name, left_out_names))
        )
        groups = ModuleGroups.from_json(settings.get(ArchitectureKey.GROUPS, []))
        kinds = {kind.kind: kind for kind in Diagram.concrete_subclasses()}
        diagrams = tuple(
            kinds[DiagramKind(table[ArchitectureKey.KIND])].from_json(
                table, groups=groups, left_out_bases=left_out_bases
            )
            for table in settings[ArchitectureKey.DIAGRAMS]
        )
        return cls(
            path=root / settings[ArchitectureKey.README],
            package=PythonPackage(directory=root / settings[ArchitectureKey.PACKAGE]),
            diagrams=diagrams,
        )

    def current_text(self) -> str:
        """
        :return: The README's text with every diagram drawn anew from the package's
            current source.
        :raises MissingDiagramMarkerError: If the README lacks a diagram's comments.
        """
        text = self.path.read_text()
        for diagram in self.diagrams:
            start = DiagramMarker.START.comment(diagram.key)
            end = DiagramMarker.END.comment(diagram.key)
            before, found_start, rest = text.partition(start)
            _, found_end, after = rest.partition(end)
            for marker, found in ((start, found_start), (end, found_end)):
                if not found:
                    raise MissingDiagramMarkerError(self.path, marker)
            drawn = diagram.to_mermaid(self.package)
            block = f"{CodeFence.MERMAID}\n{drawn}{CodeFence.CLOSE}"
            text = f"{before}{start}\n{block}\n{end}{after}"
        return text

    def is_current(self) -> bool:
        """
        :return: Whether the README holds the diagrams the package's current source
            draws.
        """
        return self.path.read_text() == self.current_text()

    def write(self) -> None:
        """
        Draw every diagram anew into the README.
        """
        self.path.write_text(self.current_text())
