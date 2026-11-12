"""
Tests that hold for the package as a whole: every module, every error and every shipped
file.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import subprocess
import sys
from types import ModuleType

import pytest

import domain_model
from domain_model.exceptions import DataclassException
from domain_model.locations import PackageLocation


def module_names() -> list[str]:
    """
    :return: The import path of every module in the package.
    """
    return [
        module.name
        for module in pkgutil.walk_packages(
            domain_model.__path__, f"{domain_model.__name__}."
        )
    ]


def modules() -> list[ModuleType]:
    """
    :return: Every module in the package, imported.
    """
    return [importlib.import_module(name) for name in module_names()]


def errors() -> list[type[DataclassException]]:
    """
    :return: Every error the package declares.
    """
    return sorted(
        {
            member
            for module in modules()
            for _, member in inspect.getmembers(module, inspect.isclass)
            if issubclass(member, DataclassException)
            and member.__module__.startswith(domain_model.__name__)
        },
        key=lambda error: error.__qualname__,
    )


# %% each module stands on its own


@pytest.mark.parametrize("module", module_names())
def test_every_module_imports_on_its_own(module: str):
    """
    Each module imports in an interpreter that has imported nothing else, so an import
    cycle that only bites the module a caller reaches first cannot hide.
    """
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"], capture_output=True, text=True
    )

    assert result.returncode == 0, result.stderr


# %% errors


@pytest.mark.parametrize("error", errors(), ids=lambda error: error.__qualname__)
def test_every_error_nothing_extends_can_be_raised(error: type[DataclassException]):
    """
    An error that leaves its message or correction unimplemented stays abstract, and
    raising it would fail with a ``TypeError`` instead of reporting what went wrong.
    """
    assert error.__subclasses__() or not inspect.isabstract(error)


# %% shipped files


@pytest.mark.parametrize(
    "location", list(PackageLocation), ids=lambda member: member._name_
)
def test_every_shipped_location_exists(location: PackageLocation):
    """
    A misspelled location would only fail at the first read of it.
    """
    assert location.value.exists()
