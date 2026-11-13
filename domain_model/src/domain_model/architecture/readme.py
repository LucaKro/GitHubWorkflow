"""
A README holding diagrams of a package's architecture, each between two comments, kept
equal to what the package's current source draws.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum, StrEnum
from pathlib import Path

from domain_model.architecture.diagrams import Diagram
from domain_model.architecture.exceptions import MissingDiagramMarkerError
from domain_model.architecture.source import PythonPackage
from domain_model.markdown import CodeFence, CommentDelimiter

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


class ArchitectureReadme(ABC):
    """
    A package's README, whose diagrams are drawn from the package's source and whose
    every other line is written by hand.
    """

    @property
    @abstractmethod
    def path(self) -> Path:
        """
        :return: The README.
        """

    @property
    @abstractmethod
    def package(self) -> PythonPackage:
        """
        :return: The package its diagrams draw.
        """

    @property
    @abstractmethod
    def diagrams(self) -> list[Diagram]:
        """
        :return: The diagrams it holds.
        """

    @property
    def left_out_bases(self) -> tuple[type, ...]:
        """
        :return: The classes its class diagrams leave out, along with every class
            descending from one: enumerations and errors.
        """
        return Enum, BaseException

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
            block = f"{CodeFence.MERMAID}\n{diagram.to_mermaid(self.package)}{CodeFence.CLOSE}"
            text = f"{before}{start}\n{block}\n{end}{after}"
        return text

    def write(self) -> None:
        """
        Draw every diagram anew into the README.
        """
        self.path.write_text(self.current_text())
