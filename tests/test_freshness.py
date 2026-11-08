"""
Tests for :mod:`github_workflow.freshness`: a fork's default branch and the work branch
brought up to date without anyone asking, and what could not be.
"""

from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus

from basstler_domain_model.github.replayed_api import RecordedAnswer, ReplayedApi
from basstler_domain_model.github.routes import RepositoryRoute
from basstler_domain_model.repository import Repository

import github_workflow
from github_workflow.command_line import WorkflowCommand
from github_workflow.freshness import BranchFreshening, FreshenedStep
from github_workflow.policy import WritePolicy
from github_workflow.report_lines import Tone
from github_workflow.settings import WorkflowSettings
from github_workflow.work import BranchSwitch, WorkflowStep

from .pull_requests import pull_request
from .repositories_by_owner import RepositoriesByOwner
from .test_commands import github, run  # noqa: F401
from .test_upstream import (
    ForkInMemory,
    ForkOfTheUpstream,
    default_branch_tips,
    with_upstream,
)
from .test_work import work  # noqa: F401  (a fixture)

# %% helpers


def change_on_github(
    work: WritePolicy, repositories: RepositoriesByOwner, branch: str, name: str
) -> str:
    """
    Commit a file on a branch of the owner's repository from another clone.

    :param work: The rules of the session's clone.
    :param repositories: The scratch repositories.
    :param branch: The branch to change.
    :param name: The file written, which is also its text.
    :return: The commit pushed.
    """
    other = repositories.clone(work.remote.push_url, f"other-{name}").git
    other.run("switch", "--quiet", branch)
    (other.working_directory / name).write_text(f"{name} from elsewhere\n")
    other.run("add", name)
    other.run("commit", "--quiet", "--message", f"Write {name}")
    other.run("push", "--quiet", "origin", branch)
    return other.commit_at("HEAD")


def freshening(work: WritePolicy, base: str | None = None) -> BranchFreshening:
    """
    :param work: The rules of the session's clone.
    :param base: The branch the work branch's open pull request targets; ``None`` for
        a work branch without one.
    :return: Brings its branches up to date, the repository being no fork.
    """
    pulls = [] if base is None else [pull_request(1, "feature", base=base)]
    return BranchFreshening(
        work, ForkOfTheUpstream(forked_from=None), ForkInMemory(pulls)
    )


@dataclass(frozen=True)
class Done(WorkflowStep):
    """
    A step that only says it ran.
    """

    def run(self) -> str:
        return "done"


# %% the work branch


def test_a_work_branch_behind_its_base_is_merged_with_it(
    work: WritePolicy, repositories: RepositoriesByOwner
) -> None:
    changed = change_on_github(
        work, repositories, RepositoriesByOwner.default_branch, "b.txt"
    )

    [line] = freshening(work).lines()

    assert work.checkout.git.contains(changed, "HEAD")
    assert line.tone is Tone.NEWS


def test_a_conflicting_merge_is_left_for_the_session(
    work: WritePolicy, repositories: RepositoriesByOwner
) -> None:
    head = work.checkout.git.commit_at("HEAD")
    change_on_github(work, repositories, RepositoriesByOwner.default_branch, "a.txt")

    [line] = freshening(work).lines()

    assert work.checkout.git.commit_at("HEAD") == head
    assert line.tone is Tone.ACTION


def test_changes_in_the_working_tree_keep_the_merge_off(
    work: WritePolicy, repositories: RepositoriesByOwner
) -> None:
    head = work.checkout.git.commit_at("HEAD")
    change_on_github(work, repositories, RepositoriesByOwner.default_branch, "b.txt")
    (work.checkout.root / "a.txt").write_text("changed, not committed\n")

    [line] = freshening(work).lines()

    assert work.checkout.git.commit_at("HEAD") == head
    assert line.tone is Tone.ACTION


def test_a_stacked_branch_is_merged_with_the_branch_below(
    work: WritePolicy, repositories: RepositoriesByOwner
) -> None:
    git = work.checkout.git
    git.run("push", "--quiet", "origin", f"{RepositoriesByOwner.default_branch}:below")
    below = change_on_github(work, repositories, "below", "b.txt")
    elsewhere = change_on_github(
        work, repositories, RepositoriesByOwner.default_branch, "c.txt"
    )

    freshening(work, base="below").lines()

    assert git.contains(below, "HEAD")
    assert not git.contains(elsewhere, "HEAD")


def test_an_up_to_date_work_branch_says_nothing(work: WritePolicy) -> None:
    assert freshening(work).lines() == []


def test_the_default_branch_checked_out_is_left_alone(
    work: WritePolicy, repositories: RepositoriesByOwner
) -> None:
    BranchSwitch(work, RepositoriesByOwner.default_branch).run()
    head = work.checkout.git.commit_at("HEAD")
    change_on_github(work, repositories, RepositoriesByOwner.default_branch, "b.txt")

    assert freshening(work).lines() == []
    assert work.checkout.git.commit_at("HEAD") == head


# %% the fork's default branch


def test_a_fork_s_main_behind_its_upstream_is_fast_forwarded(
    work: WritePolicy, repositories: RepositoriesByOwner
) -> None:
    with_upstream(work, repositories, ahead=2, own=0)

    BranchFreshening(work, ForkOfTheUpstream(), ForkInMemory()).fork_lines()

    fork, upstream = default_branch_tips(work, repositories)
    assert fork == upstream


def test_a_fork_s_main_with_commits_of_its_own_is_left_for_the_person(
    work: WritePolicy, repositories: RepositoriesByOwner
) -> None:
    with_upstream(work, repositories, ahead=1, own=1)
    before = default_branch_tips(work, repositories)

    [line] = BranchFreshening(work, ForkOfTheUpstream(), ForkInMemory()).fork_lines()

    assert default_branch_tips(work, repositories) == before
    assert line.tone is Tone.ACTION


# %% before a command


def test_a_command_says_what_was_brought_up_to_date_first(
    work: WritePolicy, repositories: RepositoriesByOwner
) -> None:
    change_on_github(work, repositories, RepositoriesByOwner.default_branch, "b.txt")
    step = FreshenedStep(freshening(work), Done())

    done = step.run()

    assert done.endswith(f"; {Done().run()}")


def test_a_push_brings_the_work_branch_up_to_the_default_branch(
    github: ReplayedApi,  # noqa: F811
    repositories: RepositoriesByOwner,
    owned_url: str,
    settings: WorkflowSettings,
) -> None:
    route = RepositoryRoute(
        Repository(settings.owner, RepositoriesByOwner.repository_name)
    )
    github.answers[
        ("GET", f"/{route.pull_requests_for_head(settings.owner, 'work')}")
    ] = RecordedAnswer(HTTPStatus.OK, "[]")
    checkout = repositories.clone(owned_url, "session")
    git = checkout.git
    git.run("switch", "--quiet", "--create", "work")
    (checkout.root / "work.txt").write_text("work\n")
    git.run("add", "work.txt")
    git.run("commit", "--quiet", "--message", "Do the work")
    git.run("push", "--quiet", "--set-upstream", "origin", "work")
    other = repositories.clone(owned_url, "other").git
    (other.working_directory / "elsewhere.txt").write_text("elsewhere\n")
    other.run("add", "elsewhere.txt")
    other.run("commit", "--quiet", "--message", "Change the default branch")
    other.run("push", "--quiet", "origin", RepositoriesByOwner.default_branch)
    (checkout.root / "more.txt").write_text("more\n")
    git.run("add", "more.txt")
    git.run("commit", "--quiet", "--message", "Do more work")
    more_work = git.commit_at("HEAD")

    run(github_workflow.__name__, checkout, WorkflowCommand.PUSH)

    git.run("fetch", "--quiet", "origin")
    assert git.contains(more_work, "origin/work")
    assert git.contains(other.commit_at("HEAD"), "origin/work")
