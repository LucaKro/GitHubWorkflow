"""
A package's architecture drawn from its source, as a project's settings declare it, and
its README's diagrams kept equal to what the source draws.
"""

from __future__ import annotations

import shutil
import tomllib
from enum import Enum
from pathlib import Path

import pytest

from domain_model.architecture.diagrams import (
    ClassDiagram,
    ConceptDiagram,
    ImportDiagram,
    ModuleGroup,
    ModuleGroups,
    SubpackageDiagram,
)
from domain_model.architecture.exceptions import (
    ClassNameCollisionError,
    MissingArchitectureSettingsError,
    MissingDiagramMarkerError,
    UnknownGroupError,
    UnknownModuleError,
)
from domain_model.architecture.readme import ArchitectureReadme, DiagramMarker
from domain_model.architecture.source import PythonPackage
from domain_model.locations import PackageLocation

from .dataset.locations import ArchitectureLocation

# %% the package drawn


@pytest.fixture
def package() -> PythonPackage:
    """
    :return: The package of shapes, a canvas and pens.
    """
    return PythonPackage(directory=ArchitectureLocation.PACKAGE)


@pytest.fixture
def package_imports(package: PythonPackage) -> ImportDiagram:
    """
    :return: The diagram of which of the package's modules imports which.
    """
    return ImportDiagram(key="imports", package_name=package.name)


@pytest.fixture
def figures(package: PythonPackage) -> ModuleGroup:
    """
    :return: The canvas and the shapes, as one group.
    """
    return ModuleGroup(
        title="figures",
        module_names=(f"{package.name}.canvas", f"{package.name}.shapes"),
    )


# %% imports


def test_import_diagram_draws_a_subpackage_as_one_node(
    package: PythonPackage, package_imports: ImportDiagram
):
    """
    A subpackage is one node importing what its modules import, imports under
    ``TYPE_CHECKING`` and relative ones included.
    """
    drawn = package_imports.to_mermaid(package)

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
        key="classes",
        modules=figures,
        left_out_bases=ArchitectureReadme.default_left_out_bases,
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


# %% the central classes


def test_concept_diagram_shows_the_most_extended_and_held_classes(
    package: PythonPackage,
):
    """
    A concept diagram shows the classes most extended directly and held, how many
    classes descend from each, and the fields of one holding another.
    """
    diagram = ConceptDiagram(
        key="concepts",
        package_name=package.name,
        left_out_bases=ArchitectureReadme.default_left_out_bases,
        concept_count=3,
    )

    assert diagram.to_mermaid(package) == ArchitectureLocation.CONCEPTS.read_text()


def test_concept_diagram_refuses_two_shown_classes_of_one_name(package: PythonPackage):
    """
    Showing every class shows both classes named ``Point``, which the diagram could not
    tell apart.
    """
    diagram = ConceptDiagram(
        key="concepts",
        package_name=package.name,
        left_out_bases=ArchitectureReadme.default_left_out_bases,
        concept_count=len(package.classes),
    )

    with pytest.raises(ClassNameCollisionError):
        diagram.to_mermaid(package)


def test_subpackage_diagram_names_each_node_s_central_classes(package: PythonPackage):
    """
    A subpackage diagram names the central classes of each module or subpackage, and
    draws which of them extends or holds a class of which.
    """
    diagram = SubpackageDiagram(
        key="subpackages",
        package_name=package.name,
        left_out_bases=ArchitectureReadme.default_left_out_bases,
        classes_per_node=1,
    )

    assert diagram.to_mermaid(package) == ArchitectureLocation.SUBPACKAGES.read_text()


# %% the settings declaring the diagrams


def test_diagram_naming_an_undeclared_group_is_refused():
    """
    A diagram naming a group the settings lack could not be drawn.
    """
    settings = tomllib.loads(ArchitectureLocation.UNKNOWN_GROUP.read_text())

    with pytest.raises(UnknownGroupError):
        ClassDiagram.from_json(
            settings,
            groups=ModuleGroups(by_title={}),
            left_out_bases=ArchitectureReadme.default_left_out_bases,
        )


def test_diagram_naming_a_missing_module_is_refused(package: PythonPackage):
    """
    A diagram naming a module the package lacks, as after a rename, is refused instead
    of drawing nothing for it.
    """
    missing = f"{package.name}.missing"

    with pytest.raises(UnknownModuleError) as raised:
        ArchitectureReadme(
            path=ArchitectureLocation.README_WITHOUT_MARKERS,
            package=package,
            diagrams=(ImportDiagram(key="imports", package_name=missing),),
        )

    assert raised.value.module_name == missing


def test_project_without_settings_is_refused(tmp_path: Path):
    """
    A project declaring no diagrams has nothing to draw.
    """
    with pytest.raises(MissingArchitectureSettingsError):
        ArchitectureReadme.from_project(tmp_path)


# %% the README


def test_project_readme_is_drawn_as_its_settings_declare(tmp_path: Path):
    """
    Writing a project's README draws each diagram its settings declare between its
    comments, and keeps every other line.
    """
    project = tmp_path / ArchitectureLocation.PROJECT.name
    shutil.copytree(ArchitectureLocation.PROJECT, project)
    readme = ArchitectureReadme.from_project(project)

    readme.write()

    assert readme.path.read_text() == ArchitectureLocation.README_DRAWN.read_text()


def test_readme_without_a_diagram_marker_is_refused(
    package: PythonPackage, package_imports: ImportDiagram
):
    """
    A README lacking the comments of one of its diagrams has nowhere to draw it.
    """
    readme = ArchitectureReadme(
        path=ArchitectureLocation.README_WITHOUT_MARKERS,
        package=package,
        diagrams=(package_imports,),
    )

    with pytest.raises(MissingDiagramMarkerError) as raised:
        readme.current_text()

    assert raised.value.marker == DiagramMarker.START.comment(package_imports.key)


def test_domain_model_readme_diagrams_match_the_source():
    """
    The domain model's README holds the diagrams its current source draws; the pre-
    commit hook draws them anew.
    """
    readme = ArchitectureReadme.from_project(PackageLocation.PROJECT)

    assert readme.path.read_text() == readme.current_text()
