"""
Tests for :mod:`github_workflow.command_line`: every command line the workflow runs is
declared once, and its parser, the lines naming it and who may run it follow from that.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from github_workflow.command_line import (
    CommandOption,
    PersonRuns,
    PriorityLevel,
    RunnableCommand,
    SessionRunsOnPersonsWord,
)
from github_workflow.command_steps import CommandStep
from github_workflow.findings import Priority
from github_workflow.session import WorkflowSession
from github_workflow.settings import WorkflowSettings

# %% the parser


@pytest.mark.parametrize("command", list(RunnableCommand))
def test_every_command_is_parsed_under_its_words(command: RunnableCommand) -> None:
    required = [
        word
        for argument in command.arguments
        if argument.required or not argument.is_option
        for word in argument.shown((*argument.choices, "1")[0]).split()
    ]

    parsed = RunnableCommand.parser().parse_args([*command.words, *required])

    words = [word for word in (parsed.command, parsed.action) if word]
    assert RunnableCommand.from_words(words) is command


@pytest.mark.parametrize("command", list(RunnableCommand))
def test_every_command_has_the_class_building_its_step(
    command: RunnableCommand, tmp_path: Path, settings: WorkflowSettings
) -> None:
    arguments = argparse.Namespace(
        command=command.words[0], action=(command.words[1:] or [None])[0]
    )

    step = CommandStep.from_arguments(WorkflowSession(tmp_path, settings), arguments)

    assert step.command is command


# %% lines naming a command


def test_a_line_names_the_arguments_asked_for_with_their_placeholders() -> None:
    line = RunnableCommand.SYNC.words_naming(CommandOption.ON)

    assert line == [*RunnableCommand.SYNC.words, f"{CommandOption.ON} <number>"]


def test_a_line_shows_a_value_given_in_place_of_the_placeholder() -> None:
    line = RunnableCommand.SYNC.words_naming(
        CommandOption.CONTINUE, values={CommandOption.CONTINUE: "a.py b.py"}
    )

    assert line == [*RunnableCommand.SYNC.words, f"{CommandOption.CONTINUE} a.py b.py"]


def test_a_line_naming_an_argument_the_command_lacks_is_refused() -> None:
    with pytest.raises(KeyError):
        RunnableCommand.PUSH.words_naming(CommandOption.TITLE)


# %% who runs a command


def test_a_session_describes_its_own_pull_request_on_its_own() -> None:
    assert RunnableCommand.DESCRIBE.runs_unasked(list(RunnableCommand.DESCRIBE.words))


def test_describing_another_pull_request_is_the_person_s_word() -> None:
    words = [*RunnableCommand.DESCRIBE.words, "12"]

    assert not RunnableCommand.DESCRIBE.runs_unasked(words)


@pytest.mark.parametrize(
    "command",
    [
        command
        for command in RunnableCommand
        if isinstance(command.authority, (SessionRunsOnPersonsWord, PersonRuns))
    ],
)
def test_a_command_on_the_person_s_word_is_never_run_unasked(
    command: RunnableCommand,
) -> None:
    assert not command.runs_unasked(list(command.words))


# %% priorities


@pytest.mark.parametrize("level", list(PriorityLevel))
def test_each_priority_level_has_its_label(level: PriorityLevel) -> None:
    assert Priority.at_level(level).level is level
