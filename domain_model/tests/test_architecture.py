"""
A package's architecture drawn from its source, and its README's diagrams kept equal to
what the source draws.
"""

from __future__ import annotations

import shutil
from enum import Enum
from pathlib import Path

import pytest

from domain_model.architecture.diagrams import (
    ClassDiagram,
    Diagram,
    ImportDiagram,
    ModuleGroup,
)
from domain_model.architecture.domain_model_readme import DomainModelReadme
from domain_model.architecture.exceptions import (
    ClassNameCollisionError,
    MissingDiagramMarkerError,
)
from domain_model.architecture.readme import ArchitectureReadme, DiagramMarker
from domain_model.architecture.source import PythonPackage

from .dataset.locations import ArchitectureLocation

# %% the package drawn


@pytest.fixture
def package() -> PythonPackage:
    """
    :return: The package of shapes, a canvas and pens.
    """
    return PythonPackage(directory=ArchitectureLocation.PACKAGE)


def package_imports() -> ImportDiagram:
    """
    :return: The diagram of which of the package's modules imports which.
    """
    return ImportDiagram(key="imports", package_name=ArchitectureLocation.PACKAGE.name)


@pytest.fixture
def figures() -> ModuleGroup:
    """
    :return: The canvas and the shapes, as one group.
    """
    package_name = ArchitectureLocation.PACKAGE.name
    return ModuleGroup(
        title="figures",
        module_names=(f"{package_name}.canvas", f"{package_name}.shapes"),
    )


# %% imports


def test_import_diagram_draws_a_subpackage_as_one_node(package: PythonPackage):
    """
    A subpackage is one node importing what its modules import, imports under
    ``TYPE_CHECKING`` and relative ones included.
    """
    drawn = package_imports().to_mermaid(package)

    assert drawn == ArchitectureLocation.PACKAGE_IMPORTS.read_text()


def test_import_diagram_draws_a_group_as_one_node(
    package: PythonPackage, figures: ModuleGroup
):
    """
    The modules of a group are one node, and imports inside it are not drawn.
    """
    diagram = ImportDiagram(key="imports", package_name=package.name, groups=(figures,))

    assert (
        diagram.to_mermaid(package) == ArchitectureLocation.GROUPED_IMPORTS.read_text()
    )


# %% classes


def test_class_diagram_draws_extensions_and_fields_without_left_out_classes(
    package: PythonPackage, figures: ModuleGroup
):
    """
    A class diagram draws which class extends which and which holds which in a field,
    leaving out the descendants of the bases it leaves out.
    """
    diagram = ClassDiagram(
        key="classes", modules=figures, left_out_bases=(Enum, BaseException)
    )

    assert diagram.to_mermaid(package) == ArchitectureLocation.SHAPE_CLASSES.read_text()


def test_class_diagram_refuses_two_classes_of_one_name(package: PythonPackage):
    """
    Two shown classes sharing a name could not be told apart in the diagram.
    """
    diagram = ClassDiagram(
        key="classes",
        modules=ModuleGroup(title="everything", module_names=(package.name,)),
        left_out_bases=(Enum, BaseException),
    )

    with pytest.raises(ClassNameCollisionError):
        diagram.to_mermaid(package)


# %% the README


class CopiedReadme(ArchitectureReadme):
    """
    A README of the drawn package holding its import diagram.
    """

    def __init__(self, path: Path) -> None:
        """
        :param path: The README.
        """
        self.copied_path = path

    @property
    def path(self) -> Path:
        return self.copied_path

    @property
    def package(self) -> PythonPackage:
        return PythonPackage(directory=ArchitectureLocation.PACKAGE)

    @property
    def diagrams(self) -> list[Diagram]:
        return [package_imports()]


def test_readme_writing_replaces_only_the_marked_diagram(tmp_path: Path):
    """
    Writing a README draws each diagram between its comments and keeps every other line.
    """
    readme = tmp_path / ArchitectureLocation.README_WITH_MARKERS.name
    shutil.copy(ArchitectureLocation.README_WITH_MARKERS, readme)

    CopiedReadme(readme).write()

    assert readme.read_text() == ArchitectureLocation.README_DRAWN.read_text()


def test_readme_without_a_diagram_marker_is_refused():
    """
    A README lacking the comments of one of its diagrams has nowhere to draw it.
    """
    readme = CopiedReadme(ArchitectureLocation.README_WITHOUT_MARKERS)

    with pytest.raises(MissingDiagramMarkerError) as raised:
        readme.current_text()

    assert raised.value.marker == DiagramMarker.START.comment(package_imports().key)


def test_domain_model_readme_diagrams_match_the_source():
    """
    The domain model's README holds the diagrams its current source draws; the pre-
    commit hook draws them anew.
    """
    readme = DomainModelReadme()

    assert readme.path.read_text() == readme.current_text()
