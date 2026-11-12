"""
Tests for :mod:`domain_model.git.subcommands`, and for the options the runner passes
agreeing with those :mod:`domain_model.git.reading` tells reading forms apart by.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

import pytest

from domain_model.git.commands import GitCommandResult, GitCommandRunner
from domain_model.git.exceptions import UnjudgedSubcommandError
from domain_model.git.reading import GitCall, PartlyReadingSubcommand
from domain_model.git.remotes import PushOption, Remote, RemoteBranch
from domain_model.git.revisions import BranchName, LocalBranch
from domain_model.git.subcommands import GitSubcommand, SubcommandReading
from domain_model.git.working_tree import WorkingTree

from .git_checkouts import checkout, published  # noqa: F401

# %% options


def test_an_option_given_a_value_is_its_member() -> None:
    assert PushOption.look_up(f"{PushOption.FORCE_WITH_LEASE}=main") is (
        PushOption.FORCE_WITH_LEASE
    )


def test_an_option_not_among_the_members_is_none() -> None:
    assert PushOption.look_up("--atomic") is None


@pytest.mark.parametrize(
    ("options", "reads"),
    [
        ([PushOption.QUIET, PushOption.PORCELAIN], True),
        ([PushOption.QUIET, PushOption.NO_VERIFY], False),
        ([PushOption.QUIET, "--atomic"], False),
    ],
    ids=str,
)
def test_options_read_only_when_each_is_a_member_marked_reading(
    options: list[str], reads: bool
) -> None:
    assert PushOption.only_reading(options) == reads


# %% subcommands reading in some forms


@pytest.mark.parametrize(
    "subcommand",
    [
        subcommand
        for subcommand in GitSubcommand
        if subcommand.reading is SubcommandReading.IN_SOME_FORMS
    ],
)
def test_a_subcommand_reading_in_some_forms_has_them_told_apart(
    subcommand: GitSubcommand,
) -> None:
    assert PartlyReadingSubcommand.judging(subcommand).subcommand is subcommand


def test_a_subcommand_reading_in_no_form_has_none_told_apart() -> None:
    with pytest.raises(UnjudgedSubcommandError):
        PartlyReadingSubcommand.judging(GitSubcommand.PUSH)


# %% the options the runner passes


RunnerOperation = Callable[[RemoteBranch], object]


@pytest.mark.parametrize(
    "operation",
    [
        lambda branch: WorkingTree(branch.remote.git).checked_out_branch(),
        lambda branch: Remote.configured(branch.remote.git),
        lambda branch: branch.remote.fetch(),
        lambda branch: branch.fetch(),
        lambda branch: LocalBranch(branch.remote.git, BranchName("copy")).fast_forward(
            branch.tracking_branch
        ),
        lambda branch: branch.tracking_branch.was_fetched_or_pushed(),
    ],
    ids=[
        "checked out branch",
        "configured remotes",
        "remote fetch",
        "branch fetch",
        "fast-forward",
        "remote-tracking branch's reflog",
    ],
)
def test_every_option_the_runner_passes_a_partly_reading_subcommand_is_one_of_its_own(
    published: RemoteBranch,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    operation: RunnerOperation,
) -> None:
    calls: list[GitCall] = []
    attempt = GitCommandRunner.attempt

    def recording(
        runner: GitCommandRunner,
        *arguments: str,
        environment: Mapping[str, str] | None = None,
    ) -> GitCommandResult:
        calls.append(GitCall(arguments))
        return attempt(runner, *arguments, environment=environment)

    monkeypatch.setattr(GitCommandRunner, "attempt", recording)

    operation(published)

    judged = [
        (PartlyReadingSubcommand.judging(GitSubcommand(call.subcommand)), call)
        for call in calls
        if GitSubcommand(call.subcommand).reading is SubcommandReading.IN_SOME_FORMS
    ]
    unknown = [
        option
        for form, call in judged
        for option in call.subcommand_arguments.options
        if form.options.look_up(option) is None
    ]
    assert (bool(judged), unknown) == (True, [])
