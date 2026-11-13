"""
The keys a project's ``pyproject.toml`` declares its architecture diagrams with, under
``[tool.architecture-diagrams]``, and the kinds of diagram it may declare.
"""

from __future__ import annotations

from enum import StrEnum

# %% the keys


class ArchitectureKey(StrEnum):
    """
    The keys of the table declaring a project's architecture diagrams, and of the tables
    inside it.
    """

    TOOL = "tool"
    """
    The table of every tool's settings.
    """

    TABLE = "architecture-diagrams"
    """
    The table declaring the diagrams, inside the tools' table.
    """

    README = "readme"
    """
    The README holding the diagrams, relative to the project's root.
    """

    PACKAGE = "package"
    """
    In the table: the package's directory, relative to the project's root. In an import
    diagram: the import path of the package whose inside it draws.
    """

    LEFT_OUT_BASES = "left-out-bases"
    """
    The import paths of the classes the class diagrams leave out, with their
    descendants.
    """

    GROUPS = "groups"
    """
    In the table: the groups of modules. In an import diagram: the titles of the groups
    it draws as one node each.
    """

    GROUP = "group"
    """
    The title of the group whose classes a class diagram shows.
    """

    DIAGRAMS = "diagrams"
    """
    The diagrams, in the order they are drawn.
    """

    TITLE = "title"
    """
    What a group's modules are about.
    """

    MODULES = "modules"
    """
    The import paths of a group's modules.
    """

    KEY = "key"
    """
    The name the comments marking a diagram's place in the README carry.
    """

    KIND = "kind"
    """
    The kind of a diagram.
    """

    CONCEPT_COUNT = "concept-count"
    """
    How many classes a concept diagram shows at most.
    """

    CLASSES_PER_NODE = "classes-per-node"
    """
    How many of a node's central classes a subpackage diagram names at most.
    """


# %% the kinds of diagram


class DiagramKind(StrEnum):
    """
    The kinds of diagram a project may declare.
    """

    IMPORTS = "imports"
    """
    Which modules of a package import which.
    """

    CLASSES = "classes"
    """
    Which classes of a group of modules extend and hold which.
    """

    CONCEPTS = "concepts"
    """
    The central classes of a package, each standing for its descendants.
    """

    SUBPACKAGES = "subpackages"
    """
    The modules and subpackages of a package with their central classes, and which uses
    a class of which.
    """
