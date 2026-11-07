"""
Tests for :mod:`basstler_domain_model.repository`: reading a GitHub repository out of a
reference or a remote URL.
"""

from __future__ import annotations

from urllib.parse import urlsplit

import pytest

from basstler_domain_model.exceptions import MalformedRepositoryError
from basstler_domain_model.repository import GitHubAddress, Repository

REPOSITORY = Repository("an-owner", "a-repository")
"""
The repository every well-formed reference and remote URL in these tests names.
"""

GITHUB_HOST = urlsplit(GitHubAddress.WEB).hostname
"""
GitHub's bare host, as an SSH remote URL carries it.
"""

# %% repository references


def test_repository_splits_a_reference_into_owner_and_name():
    assert Repository.parse(REPOSITORY.full_name) == REPOSITORY


def test_repository_round_trips_through_the_form_github_uses():
    assert str(Repository.parse(REPOSITORY.full_name)) == REPOSITORY.full_name


@pytest.mark.parametrize("malformed", ["no-separator", "/no-owner", "no-name/"])
def test_repository_rejects_a_reference_that_is_not_owner_and_name(malformed: str):
    """
    A half-parsed reference would silently target the wrong repository.
    """
    with pytest.raises(MalformedRepositoryError):
        Repository.parse(malformed)


@pytest.mark.parametrize(
    "url",
    [
        f"{GitHubAddress.WEB}/{REPOSITORY.full_name}.git",
        f"{GitHubAddress.WEB}/{REPOSITORY.full_name}",
        f"git@{GITHUB_HOST}:{REPOSITORY.full_name}.git",
        f"http://127.0.0.1:41729/git/{REPOSITORY.full_name}",
        f"ssh://git@{GITHUB_HOST}/{REPOSITORY.full_name}.git",
        f"file:///srv/repositories/{REPOSITORY.full_name}.git",
    ],
)
def test_repository_reads_the_owner_and_name_from_a_remote_url(url: str):
    """
    Every shape a fork remote takes names the same repository.

    A cloud session reaches GitHub through a local proxy, so the URL it sees shares
    neither host nor scheme with the one a laptop clone has.
    """
    assert Repository.from_remote_url(url) == REPOSITORY


@pytest.mark.parametrize("malformed", ["", f"{GitHubAddress.WEB}/only-one-segment"])
def test_repository_rejects_a_remote_url_naming_no_repository(malformed: str):
    with pytest.raises(MalformedRepositoryError):
        Repository.from_remote_url(malformed)


@pytest.mark.parametrize(
    "url",
    [
        f"https://gitlab.com/{REPOSITORY.full_name}.git",
        f"git@evil.example:{REPOSITORY.full_name}.git",
        f"https://example.com/mirror/{REPOSITORY.full_name}.git",
        f"http://127.0.0.1:41729/{REPOSITORY.full_name}",
    ],
)
def test_a_remote_url_off_github_names_no_repository(url: str):
    """
    Only GitHub, the local proxy a cloud session reaches it through, and a local
    directory standing in for it hold GitHub repositories.
    """
    assert not Repository.names_a_repository(url)


# %% pages


def test_a_workflow_run_url_is_the_run_s_page_under_the_repository_s_actions():
    assert REPOSITORY.workflow_run_url(7) == f"{REPOSITORY.url}/actions/runs/7"


def test_an_issue_url_is_the_issue_s_page_under_the_repository():
    assert REPOSITORY.issue_url(7) == f"{REPOSITORY.url}/issues/7"


# %% REST paths


def test_a_job_log_path_is_the_one_the_actions_api_serves_it_from():
    assert (
        REPOSITORY.job_log_path(7)
        == f"repos/{REPOSITORY.full_name}/actions/jobs/7/logs"
    )


def test_a_settings_url_is_the_settings_page_under_the_repository():
    assert REPOSITORY.settings_url == f"{REPOSITORY.url}/settings"


# %% installing from a repository


def test_a_requirement_installs_from_the_repository_at_a_reference():
    repository = Repository("an-owner", "a-repository")

    assert repository.git_requirement("a-package", "main") == (
        f"a-package @ git+{repository.url}@main"
    )


def test_a_requirement_names_the_directory_holding_the_project():
    repository = Repository("an-owner", "a-repository")

    assert repository.git_requirement("a-package", "main", "packages/one") == (
        f"{repository.git_requirement('a-package', 'main')}#subdirectory=packages/one"
    )
