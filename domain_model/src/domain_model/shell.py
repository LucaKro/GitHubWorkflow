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

    DASH = "dash"
    """
    The Debian Almquist shell.
    """

    KSH = "ksh"
    """
    The Korn shell.
    """

    FISH = "fish"
    """
    The friendly interactive shell.
    """

    EVAL = "eval"
    """
    The shell builtin running its arguments as a command line.
    """

    SOURCE = "source"
    """
    The shell builtin running the commands of the file it is given.
    """

    @property
    def reads_input(self) -> bool:
        """
        Whether, started without a command line, it runs what its input holds.
        """
        return self not in (Shell.EVAL, Shell.SOURCE)


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


class VariableAssignment(StrEnum):
    """
    The shell builtins, beside those exporting or removing one, that set a variable
    their arguments name.
    """

    READONLY = "readonly"
    """
    Sets a variable and keeps it from changing.
    """

    LOCAL = "local"
    """
    Sets a variable of the running function.
    """

    READ = "read"
    """
    Sets variables to what it reads from its input.
    """

    MAPFILE = "mapfile"
    """
    Sets an array to the lines of its input.
    """

    READARRAY = "readarray"
    """
    Sets an array to the lines of its input, the other spelling of ``mapfile``.
    """

    PRINTF = "printf"
    """
    Sets the variable ``-v`` names to what it formats.
    """

    GETOPTS = "getopts"
    """
    Sets a variable to the next option it parses.
    """

    LET = "let"
    """
    Sets variables to the arithmetic it evaluates.
    """


class FileWritingProgram(StrEnum):
    """
    Programs that change the files their arguments name.
    """

    RM = "rm"
    """
    Removes files.
    """

    UNLINK = "unlink"
    """
    Removes a file.
    """

    CHMOD = "chmod"
    """
    Changes files' permissions.
    """

    CHOWN = "chown"
    """
    Changes files' owner.
    """

    CP = "cp"
    """
    Copies files.
    """

    MV = "mv"
    """
    Moves files.
    """

    LN = "ln"
    """
    Links files.
    """

    INSTALL = "install"
    """
    Copies files and sets their permissions.
    """

    SED = "sed"
    """
    Edits files in place with ``-i``.
    """

    TEE = "tee"
    """
    Writes its input to files.
    """

    TOUCH = "touch"
    """
    Creates files.
    """

    TRUNCATE = "truncate"
    """
    Changes files' size.
    """

    DD = "dd"
    """
    Copies data to the file ``of=`` names.
    """

    RSYNC = "rsync"
    """
    Copies files.
    """


class InertProgram(StrEnum):
    """
    Programs that take their arguments as text, patterns or paths, and never run a
    command they name.
    """

    ECHO = "echo"
    """
    Prints its arguments.
    """

    PRINTF = "printf"
    """
    Prints its arguments, formatted.
    """

    CAT = "cat"
    """
    Prints files.
    """

    LS = "ls"
    """
    Lists files.
    """

    CD = "cd"
    """
    Changes the directory.
    """

    GREP = "grep"
    """
    Searches files.
    """

    RIPGREP = "rg"
    """
    Searches files, faster.
    """

    WHICH = "which"
    """
    Finds a program on the path.
    """

    TYPE = "type"
    """
    Tells what a name runs.
    """

    MAN = "man"
    """
    Shows a manual page.
    """

    WC = "wc"
    """
    Counts lines, words and bytes.
    """

    HEAD = "head"
    """
    Prints the start of its input or files.
    """

    TAIL = "tail"
    """
    Prints the end of its input or files.
    """

    SORT = "sort"
    """
    Sorts lines.
    """

    CUT = "cut"
    """
    Prints parts of lines.
    """

    TR = "tr"
    """
    Replaces characters.
    """

    DIFF = "diff"
    """
    Compares files.
    """

    TEST = "test"
    """
    Evaluates a condition.
    """

    BRACKET = "["
    """
    Evaluates a condition, the other spelling of ``test``.
    """

    MKDIR = "mkdir"
    """
    Creates directories.
    """

    BASENAME = "basename"
    """
    Prints a path's last component.
    """

    DIRNAME = "dirname"
    """
    Prints a path's directory.
    """

    REALPATH = "realpath"
    """
    Prints a path resolved.
    """

    JQ = "jq"
    """
    Filters JSON.
    """


class EnvironmentOption(StrEnum):
    """
    The options of ``env`` that come before the command it runs.
    """

    drops_every_variable: bool
    """
    Whether the command runs with no variables at all.
    """

    takes_value: bool
    """
    Whether the option is followed by a value of its own.
    """

    def __new__(
        cls, value: str, drops_every_variable: bool, takes_value: bool
    ) -> EnvironmentOption:
        member = str.__new__(cls, value)
        member._value_ = value
        member.drops_every_variable = drops_every_variable
        member.takes_value = takes_value
        return member

    IGNORE_ENVIRONMENT = "-i", True, False
    """
    Runs the command with no variables at all.
    """

    IGNORE_ENVIRONMENT_LONG = "--ignore-environment", True, False
    """
    Runs the command with no variables at all.
    """

    EMPTY_ENVIRONMENT = "-", True, False
    """
    Runs the command with no variables at all, the older way.
    """

    UNSET = "-u", False, True
    """
    Removes the variable it is followed by.
    """

    UNSET_LONG = "--unset", False, True
    """
    Removes the variable it is followed by.
    """

    DIRECTORY = "-C", False, True
    """
    Runs the command in the directory it is followed by.
    """

    DIRECTORY_LONG = "--chdir", False, True
    """
    Runs the command in the directory it is followed by.
    """


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
    def writes(self) -> bool:
        """
        Whether the word after it names a file that is written.
        """
        return self not in (
            Redirection.INPUT,
            Redirection.DUPLICATED_INPUT,
            Redirection.HERE_DOCUMENT,
            Redirection.HERE_STRING,
        )

    @property
    def takes_a_descriptor(self) -> bool:
        """
        Whether a file descriptor's number may be written right before it, as in ``2>``.
        """
        return self.value[0] in "<>"


class Quoting(StrEnum):
    """
    Where a character of a command line stands: the text that opens each place.
    """

    COMMAND = "("
    """
    In commands, at the top of the line or inside a substitution.
    """

    DOUBLE = '"'
    """
    Inside double quotes, where substitutions still run.
    """

    SINGLE = "'"
    """
    Inside single quotes, where every character is text.
    """

    ANSI_C = "$'"
    """
    Inside ANSI-C quotes, where every character is text and a backslash escapes one.
    """

    BACKTICK = "`"
    """
    Inside a backtick substitution, whose text runs as commands.
    """

    @property
    def is_text(self) -> bool:
        """
        Whether nothing inside runs: no substitution, no command.
        """
        return self in (Quoting.SINGLE, Quoting.ANSI_C)


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
        shells = "|".join(shell for shell in Shell if shell.reads_input)
        return re.compile(rf"(^|[;&|(]\s*|\s)({shells})(\s+-[A-Za-z]+)*\s*($|[<|;&)])")

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

    def simple_commands(self) -> list[SimpleCommand]:
        """
        :return: Every simple command the line runs, those in command substitutions
            included, without their redirections. A here-document is data
            unless a shell reads it.
        :raises ValueError: If its quotes do not balance.
        """
        return self.split().commands

    def written_files(self) -> list[str]:
        """
        :return: Every file the line's redirections write, those in command
            substitutions included, as written on the line.
        :raises ValueError: If its quotes do not balance.
        """
        return self.split().written_files

    def split(self) -> SplitLine:
        """
        :return: The line split into its simple commands and the files its
            redirections write.
        :raises ValueError: If its quotes do not balance.
        """
        text = self._without_here_documents()
        blanked = CommandLine(text).blank_quoted_text()
        inner_lines = [
            re.sub(r"\\([`\\$])", r"\1", inner) if group == 3 else inner
            for found in self.substitution.finditer(blanked)
            for group in range(1, 4)
            if found.group(group) is not None
            for inner in [text[found.start(group) : found.end(group)]]
            if inner
        ]
        inner_splits = [CommandLine(inner).split() for inner in inner_lines]
        commands = [
            command.words for inner in inner_splits for command in inner.commands
        ]
        written = [file for inner in inner_splits for file in inner.written_files]
        read = ShellInput(text.replace("\n", " ; "))
        lexer = shlex.shlex(read, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        current: list[str] = []
        descriptor_read = False
        target: Redirection | None = None
        for word in lexer:
            operator = word and set(word) <= set(";&|()<>")
            if target is not None and not operator:
                if target.writes:
                    written.append(word)
                target = None
                continue
            if word in list(Redirection):
                if descriptor_read and Redirection(word).takes_a_descriptor:
                    current.pop()
                descriptor_read = False
                target = Redirection(word)
                continue
            target = None
            if operator:
                commands.append(current)
                current = []
                descriptor_read = False
                continue
            current.append(word)
            descriptor_read = read.ends_in_a_descriptor(word)
        commands.append(current)
        return SplitLine([SimpleCommand(words) for words in commands if words], written)

    def blank_quoted_text(self) -> str:
        """
        :return: The line with every character inside single or ANSI-C quotes made a
            space, so only what the shell substitutes is left to search; the line's
            length and every other character stay as they are.
        """
        characters = list(self.text)
        contexts = [Quoting.COMMAND]
        index = 0
        while index < len(self.text):
            character = self.text[index]
            context = contexts[-1]
            if context.is_text:
                closes = character == Quoting.SINGLE
                escapes = context is Quoting.ANSI_C and character == "\\"
                width = 2 if escapes else 1
                if closes:
                    contexts.pop()
                else:
                    characters[index : index + width] = " " * len(
                        characters[index : index + width]
                    )
                index += width
                continue
            if character == "\\":
                index += 2
                continue
            following = self.text[index : index + 2]
            if following == "$(":
                contexts.append(Quoting.COMMAND)
                index += 2
                continue
            if character == Quoting.BACKTICK:
                if context is Quoting.BACKTICK:
                    contexts.pop()
                else:
                    contexts.append(Quoting.BACKTICK)
            elif context is Quoting.DOUBLE:
                if character == Quoting.DOUBLE:
                    contexts.pop()
            elif character == Quoting.DOUBLE:
                contexts.append(Quoting.DOUBLE)
            elif following == Quoting.ANSI_C:
                contexts.append(Quoting.ANSI_C)
                index += 1
            elif character == Quoting.SINGLE:
                contexts.append(Quoting.SINGLE)
            elif character == "(":
                contexts.append(Quoting.COMMAND)
            elif character == ")" and context is Quoting.COMMAND and len(contexts) > 1:
                contexts.pop()
            index += 1
        return "".join(characters)

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


@dataclass(frozen=True)
class SplitLine:
    """
    A command line as the shell runs it: its simple commands and the files it writes.
    """

    commands: list[SimpleCommand]
    """
    Every simple command it runs, those in command substitutions included.
    """

    written_files: list[str]
    """
    Every file its redirections write, as written on the line.
    """


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
