"""
Bash command lines as the shell runs them: the programs that run other commands, the
words it reads as syntax, and a line split into the simple commands it runs.
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePath

from domain_model.class_property import classproperty

# %% programs running other commands


class Shell(StrEnum):
    """
    Programs that run commands given as a string or on their input, which are judged in
    turn.
    """

    BASH = "bash"
    """
    Bash.
    """

    SH = "sh"
    """
    The POSIX shell.
    """

    ZSH = "zsh"
    """
    The Z shell.
    """

    EVAL = "eval"
    """
    The shell builtin running its arguments as a command line.
    """


class Wrapper(StrEnum):
    """
    Programs that run another command given after their own options and arguments.
    """

    ENV = "env"
    """
    Runs a command with a changed environment.
    """

    SUDO = "sudo"
    """
    Runs a command as another user.
    """

    NOHUP = "nohup"
    """
    Runs a command immune to hangups.
    """

    TIME = "time"
    """
    Runs a command and times it.
    """

    COMMAND = "command"
    """
    The shell builtin running a command past functions and aliases.
    """

    EXEC = "exec"
    """
    The shell builtin replacing the shell with a command.
    """

    NICE = "nice"
    """
    Runs a command at another priority.
    """

    TIMEOUT = "timeout"
    """
    Runs a command with a time limit.
    """

    XARGS = "xargs"
    """
    Runs a command with arguments read from its input.
    """

    WATCH = "watch"
    """
    Runs a command repeatedly.
    """


class VariableExport(StrEnum):
    """
    The shell builtins that can export a variable to every program run after them.
    """

    EXPORT = "export"
    """
    Exports a variable.
    """

    DECLARE = "declare"
    """
    Declares a variable, exported with ``-x``.
    """

    TYPESET = "typeset"
    """
    Declares a variable, the Korn shell's spelling of ``declare``.
    """


class VariableRemoval(StrEnum):
    """
    The shell builtins that remove a variable from the environment of every program run
    after them.
    """

    UNSET = "unset"
    """
    Removes a variable.
    """


class EnvironmentOption(StrEnum):
    """
    The options of ``env`` that come before the command it runs.
    """

    IGNORE_ENVIRONMENT = "-i"
    """
    Runs the command with no variables at all.
    """

    IGNORE_ENVIRONMENT_LONG = "--ignore-environment"
    """
    Runs the command with no variables at all.
    """

    EMPTY_ENVIRONMENT = "-"
    """
    Runs the command with no variables at all, the older way.
    """

    UNSET = "-u"
    """
    Removes the variable it is followed by.
    """

    UNSET_LONG = "--unset"
    """
    Removes the variable it is followed by.
    """

    DIRECTORY = "-C"
    """
    Runs the command in the directory it is followed by.
    """

    DIRECTORY_LONG = "--chdir"
    """
    Runs the command in the directory it is followed by.
    """

    @property
    def drops_every_variable(self) -> bool:
        """:return: Whether the command runs with no variables at all."""
        return self in (
            EnvironmentOption.IGNORE_ENVIRONMENT,
            EnvironmentOption.IGNORE_ENVIRONMENT_LONG,
            EnvironmentOption.EMPTY_ENVIRONMENT,
        )

    @property
    def takes_value(self) -> bool:
        """:return: Whether the option is followed by a value of its own."""
        return self in (
            EnvironmentOption.UNSET,
            EnvironmentOption.UNSET_LONG,
            EnvironmentOption.DIRECTORY,
            EnvironmentOption.DIRECTORY_LONG,
        )


# %% syntax


class ShellKeyword(StrEnum):
    """
    The words the shell reads as syntax where a command's program would stand.
    """

    IF = "if"
    """
    Opens a conditional, whose condition runs as a command.
    """

    THEN = "then"
    """
    Opens what a condition that held runs.
    """

    ELIF = "elif"
    """
    Opens a further condition.
    """

    ELSE = "else"
    """
    Opens what runs when no condition held.
    """

    FI = "fi"
    """
    Closes a conditional.
    """

    WHILE = "while"
    """
    Opens a loop running while its condition holds.
    """

    UNTIL = "until"
    """
    Opens a loop running until its condition holds.
    """

    DO = "do"
    """
    Opens a loop's body.
    """

    DONE = "done"
    """
    Closes a loop.
    """

    OPENING_BRACE = "{"
    """
    Opens a group of commands run in the current shell.
    """

    CLOSING_BRACE = "}"
    """
    Closes a group of commands.
    """

    NEGATION = "!"
    """
    Negates the status of the command after it.
    """

    FUNCTION = "function"
    """
    Defines the function the following word names.
    """

    FOR = "for"
    """
    Starts a loop whose header names a variable and its values, and runs nothing.
    """

    SELECT = "select"
    """
    Starts a menu whose header names a variable and its values, and runs nothing.
    """

    CASE = "case"
    """
    Starts a branching whose header names the word matched, and runs nothing.
    """


class Redirection(StrEnum):
    """
    An operator sending a command's input or output elsewhere; the word after it is
    where, and never part of the command.
    """

    OUTPUT = ">"
    """
    Writes the output to a file.
    """

    APPENDED_OUTPUT = ">>"
    """
    Appends the output to a file.
    """

    FORCED_OUTPUT = ">|"
    """
    Writes the output to a file, even one the shell keeps from being overwritten.
    """

    DUPLICATED_OUTPUT = ">&"
    """
    Sends the output where another file descriptor goes.
    """

    INPUT = "<"
    """
    Reads the input from a file.
    """

    DUPLICATED_INPUT = "<&"
    """
    Reads the input from another file descriptor.
    """

    INPUT_AND_OUTPUT = "<>"
    """
    Opens a file for both.
    """

    HERE_DOCUMENT = "<<"
    """
    Reads the input from the lines up to the word after it.
    """

    HERE_STRING = "<<<"
    """
    Reads the input from the word after it.
    """

    BOTH_OUTPUTS = "&>"
    """
    Writes the output and the errors to a file.
    """

    BOTH_OUTPUTS_APPENDED = "&>>"
    """
    Appends the output and the errors to a file.
    """

    @property
    def takes_a_descriptor(self) -> bool:
        """
        Whether a file descriptor's number may be written right before it, as in ``2>``.
        """
        return self.value[0] in "<>"


@dataclass
class ShellInput:
    """
    A command line read one character at a time, which knows where its reading stands.
    """

    text: str
    """
    The command line.
    """

    position: int = 0
    """
    How many characters were read.
    """

    def read(self, size: int = 1) -> str:
        """
        :param size: How many characters to read.
        :return: The next ones.
        """
        start = self.position
        self.position = min(len(self.text), start + size)
        return self.text[start : self.position]

    def readline(self) -> str:
        """
        :return: The rest of the current line, its line break included.
        """
        end = self.text.find("\n", self.position)
        return self.read(len(self.text) - self.position if end < 0 else end + 1)

    def ends_in_a_descriptor(self, word: str) -> bool:
        """
        :param word: The word just read.
        :return: Whether it is a file descriptor's number, unquoted and standing alone,
            written right before the operator read after it.
        """
        before = self.text[: self.position - 1]
        if not word.isdigit() or self.text[self.position - 1] not in "<>":
            return False
        if not before.endswith(word):
            return False
        start = len(before) - len(word)
        return start == 0 or before[start - 1] in " \t;&|()"


@dataclass(frozen=True)
class CommandLine:
    """
    One Bash command line, split the way the shell runs it.
    """

    text: str
    """
    The command line.
    """

    @classproperty
    def assignment(cls) -> re.Pattern[str]:
        """
        A word assigning an environment variable, as ``NAME=value``.
        """
        return re.compile(r"[A-Za-z_][A-Za-z0-9_]*=.*", re.DOTALL)

    @classproperty
    def here_document(cls) -> re.Pattern[str]:
        """
        The start of a here-document, capturing the word that ends it; a here-string
        (``<<<``) is not one.
        """
        return re.compile(r"(?<!<)<<(?!<)-?\s*\\?['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?")

    @classproperty
    def shell_reading_input(cls) -> re.Pattern[str]:
        """
        A shell started without a command line, which runs what its input holds.
        """
        return re.compile(
            r"(^|[;&|(]\s*|\s)(bash|sh|zsh)(\s+-[A-Za-z]+)*\s*($|[<|;&)])"
        )

    @classproperty
    def substitution(cls) -> re.Pattern[str]:
        """
        A command or process substitution, ``$(...)``, ``<(...)`` or a backtick pair,
        whose command is its one group that matched; a ``$`` or a backtick escaped by a
        backslash starts none, and a backtick escaped inside one does not end it but,
        unescaped as the shell does, starts one nested in its command.
        """
        unescaped = r"(?<!\\)(?:\\\\)*"
        return re.compile(
            rf"{unescaped}\$\(([^()]*)\)"
            r"|<\(([^()]*)\)"
            rf"|{unescaped}`((?:[^`\\]|\\.)*)`"
        )

    def simple_commands(self) -> list[list[str]]:
        """
        :return: The words of every simple command the line runs, those in command
            substitutions included, without their redirections. A here-document is data
            unless a shell reads it.
        :raises ValueError: If its quotes do not balance.
        """
        text = self._without_here_documents()
        nested = re.findall(self.substitution, text)
        inner_lines = [
            inner
            for dollar, process, backtick in nested
            for inner in (dollar, process, re.sub(r"\\([`\\$])", r"\1", backtick))
            if inner
        ]
        commands = [
            command
            for inner in inner_lines
            for command in CommandLine(inner).simple_commands()
        ]
        read = ShellInput(text.replace("\n", " ; "))
        lexer = shlex.shlex(read, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        current: list[str] = []
        descriptor_read = False
        target_follows = False
        for word in lexer:
            operator = word and set(word) <= set(";&|()<>")
            if target_follows and not operator:
                target_follows = False
                continue
            if word in list(Redirection):
                if descriptor_read and Redirection(word).takes_a_descriptor:
                    current.pop()
                descriptor_read = False
                target_follows = True
                continue
            target_follows = False
            if operator:
                commands.append(current)
                current = []
                descriptor_read = False
                continue
            current.append(word)
            descriptor_read = read.ends_in_a_descriptor(word)
        commands.append(current)
        return [command for command in commands if command]

    def runs_input_through_a_shell(self) -> bool:
        """
        :return: Whether a shell runs whatever reaches its input, which the command
            line itself does not show.
        """
        return bool(self.shell_reading_input.search(self.text))

    def _without_here_documents(self) -> str:
        """
        :return: The line with the body of every here-document no shell reads removed.
        """
        kept = []
        ending: str | None = None
        for line in self.text.split("\n"):
            if ending is not None:
                if line.strip() == ending:
                    ending = None
                continue
            kept.append(line)
            opened = self.here_document.search(line)
            if opened and not self.shell_reading_input.search(line):
                ending = opened.group(1)
        return "\n".join(kept)


# %% one simple command


@dataclass(frozen=True)
class SimpleCommand:
    """
    One simple command, split into words the way the shell runs it.
    """

    words: Sequence[str]
    """
    The command's words, shell syntax and variable assignments before its program
    included.
    """

    @property
    def program_start(self) -> int:
        """
        The position of the word naming the program run, past shell syntax, a defined
        function's name and variable assignments; the number of words when none runs.
        """
        index = 0
        while index < len(self.words):
            word = self.words[index]
            if word in (ShellKeyword.FOR, ShellKeyword.SELECT, ShellKeyword.CASE):
                return len(self.words)
            if word == ShellKeyword.FUNCTION:
                index += 2
                continue
            syntax = word in ShellKeyword
            if not syntax and not CommandLine.assignment.fullmatch(word):
                return index
            index += 1
        return index

    @property
    def assignments(self) -> list[str]:
        """
        The variables assigned for the program, as ``NAME=value``.
        """
        return [
            word
            for word in self.words[: self.program_start]
            if CommandLine.assignment.fullmatch(word)
        ]

    @property
    def program(self) -> str:
        """
        The name of the program run, empty when none runs.
        """
        if self.program_start == len(self.words):
            return ""
        return PurePath(self.words[self.program_start]).name

    @property
    def arguments(self) -> list[str]:
        """
        What follows the program's name.
        """
        return list(self.words[self.program_start + 1 :])
