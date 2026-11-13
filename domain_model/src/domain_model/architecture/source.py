"""
A Python package as its source reads, without importing it: its modules, what each
imports, and the classes each defines.
"""

from __future__ import annotations

import ast
import builtins
import pkgutil
from collections.abc import Iterator
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

# %% a module


@dataclass(frozen=True)
class PythonModule:
    """
    One module of a package, as its source file reads.
    """

    name: str
    """
    Its import path, such as ``domain_model.git.remotes``; a package's ``__init__`` is
    named after the package.
    """

    path: Path
    """
    Its source file.
    """

    @cached_property
    def syntax(self) -> ast.Module:
        """:return: Its source, parsed."""
        return ast.parse(self.path.read_text(), filename=str(self.path))

    @property
    def is_package(self) -> bool:
        """:return: Whether it is a package's ``__init__``."""
        return self.path.stem == "__init__"

    def absolute_module_name(self, statement: ast.ImportFrom) -> str:
        """
        :param statement: A ``from ... import ...`` statement of this module.
        :return: The import path of the module it imports from, relative imports
            resolved.
        """
        if not statement.level:
            return statement.module or ""
        own_package = self.name if self.is_package else self.name.rpartition(".")[0]
        parts = own_package.split(".")
        base = parts[: len(parts) - statement.level + 1]
        return ".".join([*base, *filter(None, [statement.module])])

    @cached_property
    def bound_names(self) -> dict[str, str]:
        """
        :return: The import path each name this module binds at its top refers to: the
            names its imports bind, those under ``TYPE_CHECKING`` included, and the
            classes it defines.
        """
        bound = {}
        for statement in ast.walk(self.syntax):
            if isinstance(statement, ast.Import):
                for alias in statement.names:
                    bound[alias.asname or alias.name.partition(".")[0]] = (
                        alias.name if alias.asname else alias.name.partition(".")[0]
                    )
            if isinstance(statement, ast.ImportFrom):
                source = self.absolute_module_name(statement)
                for alias in statement.names:
                    bound[alias.asname or alias.name] = f"{source}.{alias.name}"
        for definition in self.syntax.body:
            if isinstance(definition, ast.ClassDef):
                bound[definition.name] = f"{self.name}.{definition.name}"
        return bound

    def imported_names(self) -> Iterator[str]:
        """
        :return: The import path of everything this module imports, those under
            ``TYPE_CHECKING`` included: a module, or a name inside one.
        """
        for statement in ast.walk(self.syntax):
            if isinstance(statement, ast.Import):
                yield from (alias.name for alias in statement.names)
            if isinstance(statement, ast.ImportFrom):
                source = self.absolute_module_name(statement)
                yield from (f"{source}.{alias.name}" for alias in statement.names)

    def resolve(self, expression: ast.expr) -> str | None:
        """
        :param expression: A name, attribute or subscript in this module.
        :return: The import path of what it refers to, ``None`` for an expression that
            names nothing, or a name bound neither here nor among the builtins.
        """
        match expression:
            case ast.Name(id=name) if name in self.bound_names:
                return self.bound_names[name]
            case ast.Name(id=name) if name in vars(builtins):
                return f"{builtins.__name__}.{name}"
            case ast.Attribute(value=owner, attr=attribute):
                resolved = self.resolve(owner)
                return None if resolved is None else f"{resolved}.{attribute}"
            case ast.Subscript(value=generic):
                return self.resolve(generic)
        return None

    def classes(self) -> list[PythonClass]:
        """
        :return: The classes defined at this module's top, in the order it defines them.
        """
        return [
            PythonClass(module=self, syntax=definition)
            for definition in self.syntax.body
            if isinstance(definition, ast.ClassDef)
        ]


# %% a class


@dataclass(frozen=True)
class PythonClass:
    """
    One class defined at the top of a module.
    """

    module: PythonModule
    """
    The module defining it.
    """

    syntax: ast.ClassDef
    """
    Its definition.
    """

    @property
    def qualified_name(self) -> str:
        """:return: Its import path, such as ``domain_model.git.remotes.Remote``."""
        return f"{self.module.name}.{self.syntax.name}"

    def base_names(self) -> list[str]:
        """
        :return: The import path of each class it extends, in the order it lists them.
        """
        resolved = map(self.module.resolve, self.syntax.bases)
        return [name for name in resolved if name is not None]

    def field_types(self) -> dict[str, set[str]]:
        """
        :return: For each field annotated in its body, the import path of every name its
            annotation mentions.
        """
        return {
            statement.target.id: self.annotation_names(statement.annotation)
            for statement in self.syntax.body
            if isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
        }

    def annotation_names(self, annotation: ast.expr) -> set[str]:
        """
        :param annotation: An annotation in its body.
        :return: The import path of every name the annotation mentions.
        """
        if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
            return self.annotation_names(ast.parse(annotation.value, mode="eval").body)
        mentioned = [
            self.module.resolve(part)
            for part in ast.walk(annotation)
            if isinstance(part, ast.Name | ast.Attribute)
        ]
        return {name for name in mentioned if name is not None}


# %% a package


@dataclass(frozen=True)
class PythonPackage:
    """
    A top-level package and every module under it, as its source reads.
    """

    directory: Path
    """
    The package's directory, holding its ``__init__.py``.
    """

    @property
    def name(self) -> str:
        """:return: Its import path."""
        return self.directory.name

    @cached_property
    def modules(self) -> dict[str, PythonModule]:
        """:return: Each of its modules, under its import path, sorted by it."""
        found = [
            PythonModule(name=self.module_name(path), path=path)
            for path in self.directory.rglob("*.py")
        ]
        ordered = sorted(found, key=lambda module: module.name)
        return {module.name: module for module in ordered}

    def module_name(self, path: Path) -> str:
        """
        :param path: One of its source files.
        :return: The import path of the module the file holds.
        """
        relative = path.relative_to(self.directory.parent).with_suffix("")
        parts = relative.parts[:-1] if relative.stem == "__init__" else relative.parts
        return ".".join(parts)

    @cached_property
    def classes(self) -> dict[str, PythonClass]:
        """:return: Every class its modules define, under its import path."""
        return {
            defined.qualified_name: defined
            for module in self.modules.values()
            for defined in module.classes()
        }

    def imported_modules(self, module: PythonModule) -> set[str]:
        """
        :param module: One of its modules.
        :return: The import path of each of its own modules the module imports, a name
            imported from one counted as the module.
        """
        return {
            name if name in self.modules else name.rpartition(".")[0]
            for name in module.imported_names()
            if name in self.modules or name.rpartition(".")[0] in self.modules
        }

    def ancestor_names(self, qualified_name: str) -> set[str]:
        """
        :param qualified_name: The import path of a class, its own or any other.
        :return: The import paths of the class and of every class it descends from; a
            class outside the package is imported to read them.
        """
        if qualified_name in self.classes:
            ancestors = map(
                self.ancestor_names, self.classes[qualified_name].base_names()
            )
            return {qualified_name}.union(*ancestors)
        found = pkgutil.resolve_name(qualified_name)
        if not isinstance(found, type):
            return {qualified_name}
        return {
            f"{ancestor.__module__}.{ancestor.__qualname__}"
            for ancestor in found.__mro__
        }
