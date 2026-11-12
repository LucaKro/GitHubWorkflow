"""
Tests for :class:`domain_model.github.credential.GitHubToken`: the environment's token
first, then the one ``gh`` is logged in with.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from domain_model.commands import CommandRunner
from domain_model.environment import GitHubCredentialVariable
from domain_model.github.credential import GitHubToken
from domain_model.github.exceptions import GitHubCredentialUnavailableError

from .dataset.locations import DatasetLocation

# %% fixtures


@pytest.fixture
def no_token_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Unset every variable a token is read from.
    """
    for variable in GitHubCredentialVariable:
        monkeypatch.delenv(variable, raising=False)


@pytest.fixture
def logged_in_gh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """:return: The token a ``gh`` put first on ``PATH`` is logged in with."""
    directory = tmp_path / "bin"
    directory.mkdir()
    shutil.copy(DatasetLocation.GH_STUB, directory / "gh")
    (directory / "gh").chmod(0o755)
    monkeypatch.setenv("PATH", f"{directory}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("STUB_TOKEN", "a-logged-in-token")
    return "a-logged-in-token"


# %% finding it


def test_the_environment_s_token_comes_first(monkeypatch, tmp_path, logged_in_gh):
    monkeypatch.setenv(GitHubCredentialVariable.GH_TOKEN, "an-environment-token")

    assert GitHubToken(CommandRunner(tmp_path)).find() == "an-environment-token"


def test_without_one_the_token_gh_is_logged_in_with_is_used(
    no_token_variable, tmp_path, logged_in_gh
):
    assert GitHubToken(CommandRunner(tmp_path)).find() == logged_in_gh


def test_without_either_no_token_is_found(no_token_variable, tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))

    with pytest.raises(GitHubCredentialUnavailableError):
        GitHubToken(CommandRunner(tmp_path)).find()
