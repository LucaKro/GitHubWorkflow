"""
Diagrams of a package's architecture, each drawn from its source as Mermaid text that is
the same for the same source.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass
from types import ModuleType

from domain_model.architecture.exceptions import ClassNameCollisionError
from domain_model.architecture.source import PythonClass, PythonPackage

# %% a diagram


@dataclass(frozen=True)
class Diagram(ABC):
    """
    One diagram of a package, drawn from its source.
    """

    key: str
    """
    The name the comments marking the diagram's place in a README carry.
    """

    @abstractmethod
    def to_mermaid(self, package: PythonPackage) -> str:
        """
        :param package: The package to draw.
        :return: The diagram as Mermaid text, one statement per line, each line ended.
        """


# %% modules drawn together


@dataclass(frozen=True)
class ModuleGroup:
    """
    Modules of a package drawn together: as one node of an import diagram, or in one
    class diagram.
    """

    title: str
    """
    What the modules are about, as a diagram shows it.
    """

    module_names: tuple[str, ...]
    """
    The import paths of its modules; a package's stands for every module under it.
    """

    @classmethod
    def from_modules(cls, *, title: str, modules: list[ModuleType]) -> ModuleGroup:
        """
        :param title: What the modules are about.
        :param modules: The modules, packages standing for every module under them.
        :return: The group of the modules.
        """
        return cls(
            title=title, module_names=tuple(module.__name__ for module in modules)
        )

    @property
    def node_id(self) -> str:
        """:return: The identifier a Mermaid diagram gives its node."""
        return re.sub(r"\W", "_", self.title)

    def covers(self, module_name: str) -> bool:
        """
        :param module_name: The import path of a module.
        :return: Whether the module is one of the group's.
        """
        return any(
            module_name == member or module_name.startswith(f"{member}.")
            for member in self.module_names
        )


# %% which modules import which


@dataclass(frozen=True)
class ImportDiagram(Diagram):
    """
    The modules and subpackages directly inside a package, and which of them imports
    which; a subpackage, or a group of modules, is one node, importing what any module
    in it imports.
    """

    package_name: str
    """
    The import path of the package whose inside it draws.
    """

    groups: tuple[ModuleGroup, ...] = ()
    """
    The modules drawn as one node each, those of no group drawn on their own.
    """

    def containing_node(self, module_name: str) -> ModuleGroup | None:
        """
        :param module_name: The import path of a module of the package being drawn.
        :return: The node drawing the module: its group, or the module or subpackage
            directly inside the drawn package that holds it; ``None`` when the module
            lies outside the drawn package or is the package itself.
        """
        prefix = f"{self.package_name}."
        if not module_name.startswith(prefix):
            return None
        grouped = [group for group in self.groups if group.covers(module_name)]
        if grouped:
            return grouped[0]
        child = module_name.removeprefix(prefix).partition(".")[0]
        return ModuleGroup(title=child, module_names=(f"{prefix}{child}",))

    def to_mermaid(self, package: PythonPackage) -> str:
        drawn = defaultdict(list)
        for module in package.modules.values():
            drawn[self.containing_node(module.name)].append(module)
        drawn.pop(None, None)
        imports = {
            (importer, imported)
            for module in package.modules.values()
            for importer in [self.containing_node(module.name)]
            for imported in map(self.containing_node, package.imported_modules(module))
            if importer in drawn and imported in drawn and importer != imported
        }
        nodes = [
            (
                f'    {node.node_id}[["{node.title}"]]'
                if len(modules) > 1 or modules[0].is_package
                else f'    {node.node_id}["{node.title}"]'
            )
            for node, modules in sorted(drawn.items(), key=lambda item: item[0].title)
        ]
        edges = sorted(
            f"    {importer.node_id} --> {imported.node_id}"
            for importer, imported in imports
        )
        return "\n".join(["flowchart LR", *nodes, *edges, ""])


# %% which classes extend and hold which


@dataclass(frozen=True)
class ClassDiagram(Diagram):
    """
    The classes some modules of a package define: which extends which, and which holds
    which in a field.
    """

    modules: ModuleGroup
    """
    The modules whose classes it shows.
    """

    left_out_bases: tuple[type, ...]
    """
    The classes it leaves out, along with every class descending from one.
    """

    def shown_classes(self, package: PythonPackage) -> list[PythonClass]:
        """
        :param package: The package being drawn.
        :return: The classes the diagram shows, in the order their modules define them.
        """
        left_out = {
            f"{base.__module__}.{base.__qualname__}" for base in self.left_out_bases
        }
        return [
            defined
            for module in package.modules.values()
            if self.modules.covers(module.name)
            for defined in module.classes()
            if left_out.isdisjoint(package.ancestor_names(defined.qualified_name))
        ]

    def raise_on_name_collision(self, shown: list[PythonClass]) -> None:
        """
        :param shown: The classes the diagram shows.
        :raises ClassNameCollisionError: If two of them share a name.
        """
        named = defaultdict(list)
        for defined in shown:
            named[defined.syntax.name].append(defined.qualified_name)
        for qualified_names in named.values():
            if len(qualified_names) > 1:
                raise ClassNameCollisionError(self.key, qualified_names)

    def to_mermaid(self, package: PythonPackage) -> str:
        shown = self.shown_classes(package)
        self.raise_on_name_collision(shown)
        names = {defined.qualified_name: defined.syntax.name for defined in shown}
        nodes = [f"    class {defined.syntax.name}" for defined in shown]
        extensions = [
            f"    {names[base]} <|-- {defined.syntax.name}"
            for defined in shown
            for base in defined.base_names()
            if base in names
        ]
        fields = [
            f"    {defined.syntax.name} --> {names[held]} : {field_name}"
            for defined in shown
            for field_name, types in defined.field_types().items()
            for held in sorted(types)
            if held in names
        ]
        return "\n".join(
            ["classDiagram", "    direction LR", *nodes, *extensions, *fields, ""]
        )
