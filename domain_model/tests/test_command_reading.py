"""
Tests for which git and GitHub calls only read: :mod:`domain_model.git.reading` and
:mod:`domain_model.github.reading_calls`.
"""

from __future__ import annotations

import pytest

from domain_model.git.reading import (
    GitCall,
    GitCallEffect,
    ProgramRunningOption,
    UnknownGlobalOption,
    WritingSubcommand,
)
from domain_model.github.reading_calls import (
    ApiSending,
    GitHubCliCall,
    GitHubCliEffect,
    GraphQLWrite,
    HttpClient,
    WritingGitHubCliCommand,
)

# %% git


@pytest.mark.parametrize(
    "arguments",
    [
        ["log", "--oneline"],
        ["-C", "elsewhere", "status"],
        ["branch", "--list"],
        ["remote", "-v"],
        ["config", "user.name"],
        ["stash", "list"],
        ["reflog"],
        ["fetch", "origin", "+refs/heads/main:refs/remotes/origin/main"],
        ["fetch", "--prune", "origin"],
        ["branch", "--sort=-committerdate", "--format=%(refname)"],
        ["archive", "-o", "out.tar", "HEAD"],
    ],
)
def test_a_reading_git_call_has_no_effect(arguments: list[str]):
    assert GitCall(arguments).effect() is None


@pytest.mark.parametrize(
    ("arguments", "effect"),
    [
        (["--git-dir=x", "log"], UnknownGlobalOption),
        (["ls-remote", "--upload-pack=x", "origin"], ProgramRunningOption),
        (["grep", "-O", "needle"], ProgramRunningOption),
        (["push"], WritingSubcommand),
        (["branch", "feature"], WritingSubcommand),
        (["config", "user.name", "Someone"], WritingSubcommand),
        (["fetch", "origin", "main:main"], WritingSubcommand),
        (["fetch", "--set-upstream", "origin", "main"], WritingSubcommand),
        (["branch", "--edit-description"], WritingSubcommand),
        (["archive", "-o", ".git/hooks/pre-push", "HEAD"], WritingSubcommand),
    ],
)
def test_a_git_call_beyond_reading_names_what_it_does(
    arguments: list[str], effect: type[GitCallEffect]
):
    assert type(GitCall(arguments).effect()) is effect


def test_a_writing_git_call_s_effect_writes_with_its_subcommand():
    call = GitCall(["-C", "elsewhere", "push", "origin"])

    assert call.effect().write == call.subcommand


def test_an_unknown_global_option_s_effect_carries_the_option():
    call = GitCall(["--git-dir=x", "log"])

    assert call.effect() == UnknownGlobalOption(call.unknown_global_option)


def test_an_option_running_a_program_is_no_write_a_workflow_command_does():
    assert GitCall(["grep", "-O", "needle"]).effect().write is None


def test_a_git_call_names_its_subcommand_past_the_global_options():
    assert GitCall(["-C", "elsewhere", "--no-pager", "log"]).subcommand == "log"


# %% gh


@pytest.mark.parametrize(
    "arguments",
    [
        ["pr", "view", "3"],
        ["search", "prs", "--author", "someone"],
        ["api", "repos/owner/name"],
        ["api", "-X", "GET", "repos/owner/name"],
        ["api", "graphql", "-f", "query={ viewer { login } }"],
    ],
)
def test_a_reading_gh_call_has_no_effect(arguments: list[str]):
    assert GitHubCliCall(arguments).effect() is None


@pytest.mark.parametrize(
    ("arguments", "effect"),
    [
        (["pr", "create", "--title", "x"], WritingGitHubCliCommand),
        (["api", "-X", "POST", "repos/owner/name/issues"], ApiSending),
        (["api", "repos/owner/name/labels", "-f", "name=x"], ApiSending),
        (
            ["api", "graphql", "-f", "query=mutation { addStar }"],
            GraphQLWrite,
        ),
    ],
)
def test_a_gh_call_beyond_reading_names_what_it_does(
    arguments: list[str], effect: type[GitHubCliEffect]
):
    assert type(GitHubCliCall(arguments).effect()) is effect


def test_a_writing_gh_call_s_effect_writes_with_its_command():
    call = GitHubCliCall(["pr", "create", "--title", "x"])

    assert call.effect().write == call.command


def test_a_gh_command_is_named_by_its_first_two_words():
    assert GitHubCliCall(["pr", "edit", "9", "--title", "x"]).command == "pr edit"


# %% HTTP clients


def test_a_client_posting_to_github_sends_to_it():
    assert HttpClient.CURL.sends_to_github(["-X", "POST", "https://api.github.com/x"])


def test_a_client_reading_from_github_sends_nothing():
    assert not HttpClient.WGET.sends_to_github(["https://github.com/owner/name"])


def test_a_client_posting_elsewhere_sends_nothing_to_github():
    assert not HttpClient.CURL.sends_to_github(["--data", "x", "https://example.com"])
