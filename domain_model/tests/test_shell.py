"""
Tests for :mod:`domain_model.shell`: a Bash command line split into the simple commands
it runs.
"""

from __future__ import annotations

from domain_model.shell import CommandLine, SimpleCommand

# %% splitting a line


def test_a_line_is_split_at_its_operators():
    assert CommandLine("cd here && git log | head").simple_commands() == [
        SimpleCommand(["cd", "here"]),
        SimpleCommand(["git", "log"]),
        SimpleCommand(["head"]),
    ]


def test_a_substitution_s_command_is_split_out_too():
    commands = CommandLine("echo $(git push)").simple_commands()

    assert SimpleCommand(["git", "push"]) in commands


def test_a_redirection_s_target_is_no_word_of_the_command():
    assert CommandLine("git log > out.txt 2>&1").simple_commands() == [
        SimpleCommand(["git", "log"])
    ]


def test_a_here_document_no_shell_reads_is_data():
    line = "cat <<EOF\ngit push\nEOF"

    assert CommandLine(line).simple_commands() == [SimpleCommand(["cat"])]


def test_a_shell_reading_its_input_is_seen():
    assert CommandLine("echo x | bash").runs_input_through_a_shell()


# %% one simple command


def test_a_command_s_program_stands_past_its_assignments():
    command = SimpleCommand(["NAME=value", "git", "log"])

    assert (command.assignments, command.program, command.arguments) == (
        ["NAME=value"],
        "git",
        ["log"],
    )


def test_a_program_is_named_without_its_directory():
    assert SimpleCommand(["/usr/bin/git", "log"]).program == "git"
