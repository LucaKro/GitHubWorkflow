"""
Tests for :mod:`domain_model.python_project`: where a Python project's packages are
imported from, and the tool managing its environment.
"""

from __future__ import annotations

from pathlib import Path

from domain_model.locations import PythonProjectFile
from domain_model.python_project import DevelopmentExtra, PackageDirectories, UvTool

from .dataset.locations import DatasetLocation

# %% where the packages are imported from


def workspace(root: Path, *members: Path) -> None:
    """
    Lay out a uv workspace whose members are under ``packages``.

    :param root: Its root.
    :param members: The directories made, relative to it.
    """
    (root / PythonProjectFile.PYPROJECT).write_text(
        DatasetLocation.WORKSPACE_PYPROJECT.read_text()
    )
    for member in members:
        (root / member).mkdir(parents=True)


def test_a_workspace_member_s_source_directory_is_searched(tmp_path: Path):
    source = Path("packages") / "laid-out" / PythonProjectFile.SOURCE_DIRECTORY
    workspace(tmp_path, source, Path("packages") / "flat")

    assert PackageDirectories(tmp_path).search_path() == [
        str(tmp_path),
        str(tmp_path / "packages" / "flat"),
        str(tmp_path / source),
    ]


def test_a_directory_the_workspace_excludes_is_not_searched(tmp_path: Path):
    workspace(tmp_path, Path("packages") / "unused")

    assert PackageDirectories(tmp_path).search_path() == [str(tmp_path)]


def test_a_project_that_is_no_workspace_is_searched_in_its_source_directory(
    tmp_path: Path,
):
    (tmp_path / PythonProjectFile.SOURCE_DIRECTORY).mkdir()

    assert PackageDirectories(tmp_path).search_path() == [
        str(tmp_path / PythonProjectFile.SOURCE_DIRECTORY)
    ]


# %% the tool managing the environment


def test_a_uv_lock_declares_uv(tmp_path: Path):
    (tmp_path / PythonProjectFile.UV_LOCK).write_text("version = 1\n")

    assert UvTool().manages(tmp_path)


def test_a_tool_uv_table_declares_uv(tmp_path: Path):
    workspace(tmp_path)

    assert UvTool().manages(tmp_path)


def test_a_project_without_uv_s_files_is_not_uv_s(tmp_path: Path):
    (tmp_path / PythonProjectFile.PYPROJECT).write_text('[project]\nname = "project"\n')

    assert not UvTool().manages(tmp_path)


def test_the_setup_names_the_development_extras_only(tmp_path: Path):
    (tmp_path / PythonProjectFile.PYPROJECT).write_text(
        "[project.optional-dependencies]\n"
        f'{DevelopmentExtra.DEV} = ["pytest"]\n'
        'docs = ["sphinx"]\n'
    )
    tool = UvTool()

    assert tool.setup_command(tmp_path) == (
        f"{tool.executable} sync --extra {DevelopmentExtra.DEV}"
    )
