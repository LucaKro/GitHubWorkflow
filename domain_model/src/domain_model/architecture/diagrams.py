"""
Diagrams of a package's architecture, each drawn from its source as Mermaid text that is
the same for the same source.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass
from functools import cached_property
from typing import Any, Self

from domain_model.architecture.exceptions import (
    ClassNameCollisionError,
    UnknownGroupError,
)
from domain_model.architecture.keys import ArchitectureKey, DiagramKind
from domain_model.architecture.source import PythonClass, PythonModule, PythonPackage
from domain_model.class_family import ClassFamily
from domain_model.class_property import classproperty

# %% a diagram


@dataclass(frozen=True)
class Diagram(ClassFamily, ABC):
    """
    One diagram of a package, drawn from its source.
    """

    key: str
    """
    The name the comments marking the diagram's place in a README carry.
    """

    @classproperty
    @abstractmethod
    def kind(cls) -> DiagramKind:
        """
        The kind of diagram a project's settings declare it as.
        """

    @classmethod
    @abstractmethod
    def from_json(
        cls,
        data: dict[str, Any],
        *,
        groups: ModuleGroups,
        left_out_bases: tuple[type, ...],
    ) -> Self:
        """
        :param data: The diagram's table in a project's settings.
        :param groups: The groups of modules the settings declare.
        :param left_out_bases: The classes class diagrams leave out.
        :return: The diagram.
        :raises UnknownGroupError: If the table names a group the settings lack.
        """

    @abstractmethod
    def module_names(self) -> set[str]:
        """
        :return: The import paths of the modules and packages the diagram names.
        """

    @abstractmethod
    def to_mermaid(self, package: PythonPackage) -> str:
        """
        :param package: The package to draw.
        :return: The diagram as Mermaid text, one statement per line, each line ended.
        """


# %% classes drawn by name


@dataclass(frozen=True)
class ClassNamingDiagram(Diagram, ABC):
    """
    A diagram drawing classes by their bare name.
    """

    def raise_on_name_collision(self, shown: list[PythonClass]) -> None:
        """
        :param shown: The classes it draws.
        :raises ClassNameCollisionError: If two of them share a name.
        """
        named = defaultdict(list)
        for defined in shown:
            named[defined.syntax.name].append(defined.qualified_name)
        for qualified_names in named.values():
            if len(qualified_names) > 1:
                raise ClassNameCollisionError(self.key, qualified_names)


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
    def from_json(cls, data: dict[str, Any]) -> ModuleGroup:
        """
        :param data: The group's table in a project's settings.
        :return: The group.
        """
        return cls(
            title=data[ArchitectureKey.TITLE],
            module_names=tuple(data[ArchitectureKey.MODULES]),
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

    def kept_classes(
        self, package: PythonPackage, left_out_bases: tuple[type, ...]
    ) -> list[PythonClass]:
        """
        :param package: The package the group's modules belong to.
        :param left_out_bases: The classes left out, along with their descendants.
        :return: The classes the group's modules define and keep, in the order the
            modules define them.
        """
        left_out = {f"{base.__module__}.{base.__qualname__}" for base in left_out_bases}
        return [
            defined
            for module in package.modules.values()
            if self.covers(module.name)
            for defined in module.classes()
            if left_out.isdisjoint(package.ancestor_names(defined.qualified_name))
        ]


@dataclass(frozen=True)
class ModuleGroups:
    """
    The groups of modules a project's settings declare, by title.
    """

    by_title: dict[str, ModuleGroup]
    """
    Each group, under its title.
    """

    @classmethod
    def from_json(cls, data: list[dict[str, Any]]) -> ModuleGroups:
        """
        :param data: The groups' tables in a project's settings.
        :return: The groups.
        """
        groups = map(ModuleGroup.from_json, data)
        return cls(by_title={group.title: group for group in groups})

    def group_titled(self, title: str) -> ModuleGroup:
        """
        :param title: A group's title.
        :return: The group.
        :raises UnknownGroupError: If no group has the title.
        """
        if title not in self.by_title:
            raise UnknownGroupError(title, sorted(self.by_title))
        return self.by_title[title]


# %% the inside of a package


@dataclass(frozen=True)
class PackageContentsDiagram(Diagram, ABC):
    """
    A diagram whose nodes are the modules and subpackages directly inside a package; a
    subpackage, or a group of modules, is one node.
    """

    package_name: str
    """
    The import path of the package whose inside it draws.
    """

    groups: tuple[ModuleGroup, ...] = ()
    """
    The modules drawn as one node each, those of no group drawn on their own.
    """

    def module_names(self) -> set[str]:
        grouped = (group.module_names for group in self.groups)
        return {self.package_name}.union(*grouped)

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

    def drawn_nodes(
        self, package: PythonPackage
    ) -> dict[ModuleGroup, list[PythonModule]]:
        """
        :param package: The package being drawn.
        :return: Each node, sorted by title, with the modules it draws.
        """
        drawn = defaultdict(list)
        for module in package.modules.values():
            drawn[self.containing_node(module.name)].append(module)
        drawn.pop(None, None)
        return dict(sorted(drawn.items(), key=lambda item: item[0].title))


# %% which modules import which


@dataclass(frozen=True)
class ImportDiagram(PackageContentsDiagram):
    """
    The modules and subpackages directly inside a package, and which of them imports
    which; a node imports what any module in it imports.
    """

    @classproperty
    def kind(cls) -> DiagramKind:
        return DiagramKind.IMPORTS

    @classmethod
    def from_json(
        cls,
        data: dict[str, Any],
        *,
        groups: ModuleGroups,
        left_out_bases: tuple[type, ...],
    ) -> Self:
        titles = data.get(ArchitectureKey.GROUPS, [])
        return cls(
            key=data[ArchitectureKey.KEY],
            package_name=data[ArchitectureKey.PACKAGE],
            groups=tuple(map(groups.group_titled, titles)),
        )

    def to_mermaid(self, package: PythonPackage) -> str:
        drawn = self.drawn_nodes(package)
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
            for node, modules in drawn.items()
        ]
        edges = sorted(
            f"    {importer.node_id} --> {imported.node_id}"
            for importer, imported in imports
        )
        return "\n".join(["flowchart LR", *nodes, *edges, ""])


# %% which classes extend and hold which


@dataclass(frozen=True)
class ClassDiagram(ClassNamingDiagram):
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

    @classproperty
    def kind(cls) -> DiagramKind:
        return DiagramKind.CLASSES

    @classmethod
    def from_json(
        cls,
        data: dict[str, Any],
        *,
        groups: ModuleGroups,
        left_out_bases: tuple[type, ...],
    ) -> Self:
        return cls(
            key=data[ArchitectureKey.KEY],
            modules=groups.group_titled(data[ArchitectureKey.GROUP]),
            left_out_bases=left_out_bases,
        )

    def module_names(self) -> set[str]:
        return set(self.modules.module_names)

    def to_mermaid(self, package: PythonPackage) -> str:
        shown = self.modules.kept_classes(package, self.left_out_bases)
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


# %% how central a class is


@dataclass(frozen=True)
class ClassWeights:
    """
    Some classes of a package, each weighed by how many of them extend it and how many
    hold it in a field.
    """

    classes: dict[str, PythonClass]
    """
    The classes weighed, under their import paths.
    """

    def base_names(self, qualified_name: str) -> list[str]:
        """
        :param qualified_name: One of the classes.
        :return: The classes among them it extends directly, in the order it lists them.
        """
        bases = self.classes[qualified_name].base_names()
        return [base for base in bases if base in self.classes]

    def held_names(self, qualified_name: str) -> set[str]:
        """
        :param qualified_name: One of the classes.
        :return: The classes among them its fields name.
        """
        types = self.classes[qualified_name].field_types().values()
        return set().union(*types) & set(self.classes)

    @cached_property
    def descendants(self) -> dict[str, set[str]]:
        """:return: For each class, the classes among them descending from it."""
        found = {name: set() for name in self.classes}
        for name in self.classes:
            ancestors = self.base_names(name)
            for ancestor in ancestors:
                found[ancestor].add(name)
                ancestors += self.base_names(ancestor)
        return found

    @cached_property
    def holders(self) -> dict[str, set[str]]:
        """:return: For each class, the other classes among them holding it in a field."""
        found = {name: set() for name in self.classes}
        for name in self.classes:
            for held in self.held_names(name) - {name}:
                found[held].add(name)
        return found

    @cached_property
    def direct_subclasses(self) -> dict[str, set[str]]:
        """:return: For each class, the classes among them extending it directly."""
        found = {name: set() for name in self.classes}
        for name in self.classes:
            for base in self.base_names(name):
                found[base].add(name)
        return found

    def weight(self, qualified_name: str) -> int:
        """
        :param qualified_name: One of the classes.
        :return: How many classes extend it directly, plus how many hold it.
        """
        direct = self.direct_subclasses[qualified_name]
        return len(direct) + len(self.holders[qualified_name])

    def heaviest(self, names: set[str], count: int) -> list[str]:
        """
        :param names: Some of the classes.
        :param count: How many to keep at most.
        :return: Those that weigh anything, heaviest first, ties by import path.
        """
        weighed = [name for name in names if self.weight(name)]
        return sorted(weighed, key=lambda name: (-self.weight(name), name))[:count]


# %% the central classes


@dataclass(frozen=True)
class ConceptMap:
    """
    The heaviest classes of a package's weighed classes, each standing for the classes
    descending from it.
    """

    weights: ClassWeights
    """
    The classes weighed.
    """

    shown: tuple[str, ...]
    """
    The import paths of the classes shown, heaviest first.
    """

    def standing_for(self, qualified_name: str) -> set[str]:
        """
        :param qualified_name: One of the weighed classes.
        :return: The shown classes it counts as: itself when shown, else the nearest
            shown classes it descends from; none when it descends from none.
        """
        if qualified_name in self.shown:
            return {qualified_name}
        bases = self.weights.base_names(qualified_name)
        return set().union(*map(self.standing_for, bases))

    def label(self, qualified_name: str) -> str:
        """
        :param qualified_name: A shown class.
        :return: Its name in the diagram.
        """
        return self.weights.classes[qualified_name].syntax.name

    def node_lines(self) -> list[str]:
        """
        :return: The lines declaring each shown class, naming inside its box how many
            classes descend from it, if any do.
        """
        lines = []
        for name in self.shown:
            descendants = self.weights.descendants[name]
            if not descendants:
                lines.append(f"    class {self.label(name)}")
                continue
            noun = "subclass" if len(descendants) == 1 else "subclasses"
            lines += [
                f"    class {self.label(name)} {{",
                f"        {len(descendants)} {noun}",
                "    }",
            ]
        return lines

    def extension_lines(self) -> list[str]:
        """
        :return: A line for each shown class extending the nearest shown classes it
            descends from.
        """
        return sorted(
            {
                f"    {self.label(base)} <|-- {self.label(name)}"
                for name in self.shown
                for base_name in self.weights.base_names(name)
                for base in self.standing_for(base_name)
            }
        )

    def field_lines(self) -> list[str]:
        """
        :return: A line for each shown class holding another, or a class standing for
            it, labelled with the fields holding it.
        """
        held_in = defaultdict(set)
        for holder in self.shown:
            fields = self.weights.classes[holder].field_types().items()
            for field_name, types in fields:
                for held in types & set(self.weights.classes):
                    for target in self.standing_for(held) - {holder}:
                        held_in[self.label(holder), self.label(target)].add(field_name)
        return sorted(
            f"    {source} --> {target} : {', '.join(sorted(field_names))}"
            for (source, target), field_names in held_in.items()
        )


@dataclass(frozen=True)
class ConceptDiagram(ClassNamingDiagram):
    """
    The central classes of a package: those most extended directly and held, each
    standing for the classes descending from it.
    """

    package_name: str
    """
    The import path of the package whose classes it weighs.
    """

    left_out_bases: tuple[type, ...]
    """
    The classes left out, along with every class descending from one.
    """

    concept_count: int = 25
    """
    How many classes it shows at most.
    """

    @classproperty
    def kind(cls) -> DiagramKind:
        return DiagramKind.CONCEPTS

    @classmethod
    def from_json(
        cls,
        data: dict[str, Any],
        *,
        groups: ModuleGroups,
        left_out_bases: tuple[type, ...],
    ) -> Self:
        return cls(
            key=data[ArchitectureKey.KEY],
            package_name=data[ArchitectureKey.PACKAGE],
            left_out_bases=left_out_bases,
            concept_count=data.get(ArchitectureKey.CONCEPT_COUNT, cls.concept_count),
        )

    def module_names(self) -> set[str]:
        return {self.package_name}

    def to_mermaid(self, package: PythonPackage) -> str:
        whole = ModuleGroup(title=self.package_name, module_names=(self.package_name,))
        kept = whole.kept_classes(package, self.left_out_bases)
        weights = ClassWeights(classes={c.qualified_name: c for c in kept})
        shown = weights.heaviest(set(weights.classes), self.concept_count)
        self.raise_on_name_collision([weights.classes[name] for name in shown])
        concepts = ConceptMap(weights=weights, shown=tuple(shown))
        lines = [
            *concepts.node_lines(),
            *concepts.extension_lines(),
            *concepts.field_lines(),
        ]
        return "\n".join(["classDiagram", "    direction LR", *lines, ""])


# %% the subpackages and their central classes


@dataclass(frozen=True)
class SubpackageDiagram(PackageContentsDiagram):
    """
    The modules and subpackages directly inside a package, each with its central
    classes, and which of them extends or holds a class of which.
    """

    left_out_bases: tuple[type, ...] = ()
    """
    The classes left out, along with every class descending from one.
    """

    classes_per_node: int = 3
    """
    How many of a node's central classes it names at most.
    """

    @classproperty
    def kind(cls) -> DiagramKind:
        return DiagramKind.SUBPACKAGES

    @classmethod
    def from_json(
        cls,
        data: dict[str, Any],
        *,
        groups: ModuleGroups,
        left_out_bases: tuple[type, ...],
    ) -> Self:
        titles = data.get(ArchitectureKey.GROUPS, [])
        return cls(
            key=data[ArchitectureKey.KEY],
            package_name=data[ArchitectureKey.PACKAGE],
            groups=tuple(map(groups.group_titled, titles)),
            left_out_bases=left_out_bases,
            classes_per_node=data.get(
                ArchitectureKey.CLASSES_PER_NODE, cls.classes_per_node
            ),
        )

    def to_mermaid(self, package: PythonPackage) -> str:
        drawn = self.drawn_nodes(package)
        whole = ModuleGroup(title=self.package_name, module_names=(self.package_name,))
        kept = whole.kept_classes(package, self.left_out_bases)
        weights = ClassWeights(classes={c.qualified_name: c for c in kept})
        node_of = {
            name: self.containing_node(defined.module.name)
            for name, defined in weights.classes.items()
        }
        uses = {
            (node_of[name], node_of[used])
            for name in weights.classes
            for used in {*weights.base_names(name), *weights.held_names(name)}
            if node_of[name] != node_of[used]
        }
        nodes = []
        for node in drawn:
            own = {name for name, holder in node_of.items() if holder == node}
            central = [
                weights.classes[name].syntax.name
                for name in weights.heaviest(own, self.classes_per_node)
            ]
            label = (
                "<br>".join([node.title, ", ".join(central)]) if central else node.title
            )
            nodes.append(f'    {node.node_id}["{label}"]')
        edges = sorted(f"    {user.node_id} --> {used.node_id}" for user, used in uses)
        return "\n".join(["flowchart LR", *nodes, *edges, ""])
