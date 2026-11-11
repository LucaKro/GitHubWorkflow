"""
Tests for which git and GitHub calls only read: :mod:`domain_model.git.reading` and
:mod:`domain_model.github.reading_calls`.
"""

from __future__ import annotations

import pytest

from domain_model.git.reading import GitCall, GitCallEffect
from domain_model.github.reading_calls import (
    GitHubCliCall,
    GitHubCliEffect,
    HttpClient,
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
        (["--git-dir=x", "log"], GitCallEffect.UNKNOWN_GLOBAL_OPTION),
        (["ls-remote", "--upload-pack=x", "origin"], GitCallEffect.RUNS_A_PROGRAM),
        (["grep", "-O", "needle"], GitCallEffect.RUNS_A_PROGRAM),
        (["push"], GitCallEffect.WRITES),
        (["branch", "feature"], GitCallEffect.WRITES),
        (["config", "user.name", "Someone"], GitCallEffect.WRITES),
        (["fetch", "origin", "main:main"], GitCallEffect.WRITES),
        (["fetch", "--set-upstream", "origin", "main"], GitCallEffect.WRITES),
        (["branch", "--edit-description"], GitCallEffect.WRITES),
        (["archive", "-o", ".git/hooks/pre-push", "HEAD"], GitCallEffect.WRITES),
    ],
)
def test_a_git_call_beyond_reading_names_what_it_does(
    arguments: list[str], effect: GitCallEffect
):
    assert GitCall(arguments).effect() is effect


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
        (["pr", "create", "--title", "x"], GitHubCliEffect.WRITES),
        (["api", "-X", "POST", "repos/owner/name/issues"], GitHubCliEffect.API_SENDS),
        (["api", "repos/owner/name/labels", "-f", "name=x"], GitHubCliEffect.API_SENDS),
        (
            ["api", "graphql", "-f", "query=mutation { addStar }"],
            GitHubCliEffect.GRAPHQL_WRITE,
        ),
    ],
)
def test_a_gh_call_beyond_reading_names_what_it_does(
    arguments: list[str], effect: GitHubCliEffect
):
    assert GitHubCliCall(arguments).effect() is effect


def test_a_gh_command_is_named_by_its_first_two_words():
    assert GitHubCliCall(["pr", "edit", "9", "--title", "x"]).command == "pr edit"


# %% HTTP clients


def test_a_client_posting_to_github_sends_to_it():
    assert HttpClient.CURL.sends_to_github(["-X", "POST", "https://api.github.com/x"])


def test_a_client_reading_from_github_sends_nothing():
    assert not HttpClient.WGET.sends_to_github(["https://github.com/owner/name"])


def test_a_client_posting_elsewhere_sends_nothing_to_github():
    assert not HttpClient.CURL.sends_to_github(["--data", "x", "https://example.com"])
