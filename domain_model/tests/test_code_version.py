"""
Tests for :mod:`domain_model.code_version`: the version running and the commit it was
built from, as far as the installation tells.
"""

from __future__ import annotations

from pathlib import Path

import domain_model.code_version
from domain_model.code_version import CodeVersion, DirectUrl, DirectUrlKey
from domain_model.git.commands import GitCommandRunner
from domain_model.git.revisions import CommitHash
from domain_model.python_project import ProjectKey, Pyproject

from .git_checkouts import checkout, head  # noqa: F401

# %% the distribution's name


def test_the_project_declares_the_name_the_version_is_looked_up_under() -> None:
    project_root = Path(domain_model.code_version.__file__).parents[2]

    project = Pyproject(project_root).settings()[ProjectKey.PROJECT]

    assert project[ProjectKey.NAME] == CodeVersion.distribution_name


# %% where the installation came from


def test_an_installation_from_a_repository_names_its_commit() -> None:
    commit = "1" * 40

    source = DirectUrl.from_json(
        {
            DirectUrlKey.URL: "https://github.com/an-owner/a-repository",
            DirectUrlKey.VCS_INFO: {DirectUrlKey.COMMIT_ID: commit},
        }
    )

    assert (source.commit, source.directory) == (CommitHash(commit), None)


def test_an_installation_from_a_directory_names_it(tmp_path: Path) -> None:
    source = DirectUrl.from_json({DirectUrlKey.URL: tmp_path.as_uri()})

    assert (source.commit, source.directory) == (None, tmp_path)


# %% the commit of a checkout


def test_a_checkout_tracking_the_module_gives_its_checked_out_commit(
    checkout: GitCommandRunner,  # noqa: F811
) -> None:
    source = checkout.working_directory / "source"
    module = source / CodeVersion.module_path
    module.parent.mkdir(parents=True)
    module.write_text("")
    checkout.run("add", str(module))
    checkout.run("commit", "--quiet", "--message", "Add the module")

    assert CodeVersion.checkout_commit(source) == head(checkout)


def test_an_unrelated_checkout_enclosing_the_package_gives_no_commit(
    checkout: GitCommandRunner,  # noqa: F811
) -> None:
    environment = checkout.working_directory / "venv" / "site-packages"
    module = environment / CodeVersion.module_path
    module.parent.mkdir(parents=True)
    module.write_text("")

    assert CodeVersion.checkout_commit(environment) is None


def test_a_directory_in_no_checkout_has_no_commit(tmp_path: Path) -> None:
    assert CodeVersion.checkout_commit(tmp_path) is None


# %% the version as JSON


def test_a_version_reads_back_as_written() -> None:
    version = CodeVersion("1.2.0", CommitHash("2" * 40))

    assert CodeVersion.from_json(version.to_json()) == version


def test_a_version_not_telling_its_commit_reads_back_without_one() -> None:
    version = CodeVersion(None, None)

    assert CodeVersion.from_json(version.to_json()) == version
