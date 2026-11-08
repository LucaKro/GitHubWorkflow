"""
Tests for :class:`basstler_domain_model.git.commands.Remote`.
"""

from __future__ import annotations

from basstler_domain_model.git.commands import Remote, RemoteBranch
from basstler_domain_model.repository import Repository

# %% a remote's branches


def test_a_remote_s_branch_is_the_branch_of_that_name_on_it() -> None:
    repository = Repository.parse("owner/project")
    remote = Remote("fork", repository.clone_url, repository)

    assert remote.branch("feature") == RemoteBranch("fork", "feature")
