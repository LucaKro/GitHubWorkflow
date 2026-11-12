"""
Tests for :mod:`domain_model.git.subcommands`, and for the options the runner passes
agreeing with those :mod:`domain_model.git.reading` tells reading forms apart by.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

import pytest

from domain_model.git.commands import GitCommandResult, GitCommandRunner
from domain_model.git.options import PushOption
from domain_model.git.reading import (
    GitCall,
    GitSubcommandArguments,
    NeverReadingForms,
    PartlyReadingForms,
    ReadingForms,
)
from domain_model.git.remotes import Remote, RemoteBranch
from domain_model.git.revisions import BranchName, LocalBranch
from domain_model.git.subcommands import GitSubcommand
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


@pytest.mark.parametrize("subcommand", list(GitSubcommand))
def test_a_subcommand_s_forms_are_told_apart_by_one_member_at_most(
    subcommand: GitSubcommand,
) -> None:
    telling_apart = [
        form
        for form in ReadingForms.concrete_subclasses()
        if subcommand in form.subcommands
    ]

    assert len(telling_apart) <= 1


@pytest.mark.parametrize("form", PartlyReadingForms.concrete_subclasses())
def test_a_subcommand_reading_in_some_forms_has_them_told_apart(
    form: type[PartlyReadingForms],
) -> None:
    assert type(ReadingForms.from_subcommand(form.subcommand)) is form


def test_a_subcommand_reading_always_reads_whatever_its_arguments() -> None:
    forms = ReadingForms.from_subcommand(GitSubcommand.LOG)

    assert forms.reads(GitSubcommandArguments(["--all", "--oneline"])) is True


def test_a_subcommand_nothing_tells_forms_apart_of_reads_in_none() -> None:
    forms = ReadingForms.from_subcommand(GitSubcommand.PUSH)

    assert type(forms) is NeverReadingForms


# %% the options the runner passes


RunnerOperation = Callable[[RemoteBranch], object]


@pytest.mark.parametrize(
    "operation",
    [
        lambda branch: WorkingTree(branch.remote.git).checked_out_branch(),
        lambda branch: Remote.read_configured(branch.remote.git),
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

    def record_call(
        runner: GitCommandRunner,
        *arguments: str,
        environment: Mapping[str, str] | None = None,
    ) -> GitCommandResult:
        calls.append(GitCall(arguments))
        return attempt(runner, *arguments, environment=environment)

    monkeypatch.setattr(GitCommandRunner, "attempt", record_call)

    operation(published)

    forms = [
        (ReadingForms.from_subcommand(GitSubcommand(call.subcommand)), call)
        for call in calls
    ]
    judged = [
        (form, call) for form, call in forms if isinstance(form, PartlyReadingForms)
    ]
    unknown = [
        option
        for form, call in judged
        for option in call.subcommand_arguments.options
        if form.options.look_up(option) is None
    ]
    assert (bool(judged), unknown) == (True, [])
