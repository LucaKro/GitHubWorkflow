"""
The notes block in ``CLAUDE.local.md``: written at session start, read back on save, and
never touching anything outside its markers.
"""

from __future__ import annotations

import hashlib
import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum, StrEnum, auto

from basstler_domain_model.class_property import classproperty
from basstler_domain_model.github.discussions import DefaultDiscussionCategory
from basstler_domain_model.templates import Placeholder

from github_workflow.command_line import (
    CommandOption,
    RefusalAdvice,
    RunnableCommand,
    WorkflowCommand,
)
from github_workflow.locations import WorkflowTemplate
from github_workflow.markers import WorkflowMarker
from github_workflow.policy import Attribution

# %% the template's placeholders


class NotesHeaderPlaceholder(Placeholder):
    """
    The names the notes header's template leaves to be filled in.
    """

    SOURCE_OF_NOTES = auto()
    """
    Where the notes were read from.
    """

    SAVE_COMMAND = auto()
    """
    The command saving the notes block.
    """

    WORKFLOW_COMMAND = auto()
    """
    The command every write to git and GitHub goes through.
    """

    COMMANDS = auto()
    """
    The workflow's commands, listed.
    """

    FINDING_GUIDE = auto()
    """
    What each finding priority means.
    """

    IDEAS_CATEGORY = auto()
    """
    The discussion category ideas are posted in unless told otherwise.
    """

    REFUSAL_HINT = auto()
    """
    What a session does about a refusal.
    """

    CO_AUTHOR_TRAILER = auto()
    """
    The trailer crediting a co-author.
    """

    ACKNOWLEDGEMENT = auto()
    """
    The line every commit's message carries.
    """


# %% markers


class BlockMarker(StrEnum):
    """
    The lines that open and close the whole block.
    """

    START = WorkflowMarker("start").line()
    """
    Opens the block.
    """

    END = WorkflowMarker("end").line()
    """
    Closes the block.
    """


class NotesSection(StrEnum):
    """
    The sections of the block, each saved to a file of its own, each titled by its
    value.
    """

    STANDING_NOTES = "Standing notes"
    """
    The notes every session on the repository starts with.
    """

    BRANCH_PROGRESS = "Progress on this branch"
    """
    Plan, progress and next steps for the checked-out branch.
    """

    @property
    def start_marker(self) -> str:
        """:return: The line the section's editable text starts after."""
        return WorkflowMarker(f"{self._name_.lower()}:start").line()

    @property
    def end_marker(self) -> str:
        """:return: The line the section's editable text ends before."""
        return WorkflowMarker(f"{self._name_.lower()}:end").line()


class BlockRecord(WorkflowMarker, Enum):
    """
    The comments recording what the block was loaded with.
    """

    BRANCH = ("branch",)
    """
    The branch whose progress the block holds, empty for none.
    """

    LOADED = ("loaded",)
    """
    A digest of the sections as loaded, or as last saved.
    """


# %% commands named in the header


class ReferenceKind(StrEnum):
    """
    What a reference in the notes header names.
    """

    COMMAND = "command"
    """
    A command line, its program and the arguments listed after its name included; the
    name of a :class:`RunnableCommand`, or of a :class:`WorkflowCommand` for the command
    alone.
    """

    OPTION = "option"
    """
    A :class:`CommandOption`, by its name.
    """

    ARGUMENT = "argument"
    """
    One argument of a :class:`RunnableCommand`, with its placeholder.
    """


@dataclass(frozen=True)
class CommandReference(ABC):
    """
    A command, an option or an argument the notes header names, written as
    ``{<kind>:<name> <argument>...}``.
    """

    name: str
    """
    The member of the command or option named.
    """

    arguments: tuple[str, ...]
    """
    The arguments named after it, by their names.
    """

    @classproperty
    @abstractmethod
    def kind(cls) -> ReferenceKind:
        """
        What a reference of this class names, as the header writes it.
        """

    @abstractmethod
    def text(self, program: str) -> str:
        """
        :param program: How the command line starts.
        :return: What the reference names, as the header shows it.
        :raises KeyError: If it names a command, option or argument that does not exist.
        """

    @classmethod
    def pattern(cls) -> re.Pattern[str]:
        """
        A reference, its kind, name and arguments its three groups.
        """
        kinds = "|".join(ReferenceKind)
        return re.compile(rf"\{{({kinds}):([A-Z_]+)((?: [^}}]+)?)\}}")

    @classmethod
    def from_match(cls, found: re.Match[str]) -> CommandReference:
        """
        :param found: A match of :meth:`pattern`.
        :return: The reference it matched.
        """
        kind, name, arguments = found.groups()
        referenced = next(
            reference
            for reference in cls.__subclasses__()
            if reference.kind is ReferenceKind(kind)
        )
        return referenced(name, tuple(arguments.split()))


@dataclass(frozen=True)
class CommandLineReference(CommandReference):
    """
    A reference to a command line, shown with its program and the arguments named.
    """

    @classproperty
    def kind(cls) -> ReferenceKind:
        return ReferenceKind.COMMAND

    def text(self, program: str) -> str:
        if self.name in RunnableCommand.__members__:
            words = RunnableCommand[self.name].words_naming(*self.arguments)
        else:
            words = [WorkflowCommand[self.name]]
        return " ".join([program, *words])


@dataclass(frozen=True)
class OptionReference(CommandReference):
    """
    A reference to an option, shown as the option alone.
    """

    @classproperty
    def kind(cls) -> ReferenceKind:
        return ReferenceKind.OPTION

    def text(self, program: str) -> str:
        return CommandOption[self.name]


@dataclass(frozen=True)
class ArgumentReference(CommandReference):
    """
    A reference to one argument of a command, shown with its placeholder.
    """

    @classproperty
    def kind(cls) -> ReferenceKind:
        return ReferenceKind.ARGUMENT

    def text(self, program: str) -> str:
        [argument] = self.arguments
        return RunnableCommand[self.name].argument(argument).shown()


# %% the block


@dataclass(frozen=True)
class NotesBlock:
    """
    What a session starts with, as one block of ``CLAUDE.local.md``.
    """

    source: str
    """
    Where the notes were read from, as the header names it.
    """

    save_command: str
    """
    The command that saves edits to the block, as the header gives it.
    """

    workflow_command: str
    """
    The command every write to git and GitHub goes through, as the header gives it.
    """

    finding_guide: str
    """
    What each finding priority means, as the header gives it.
    """

    branch: str
    """
    The checked-out branch, empty on a detached ``HEAD``, which has no progress section.
    """

    sections: dict[NotesSection, str]
    """
    The text of each section.
    """

    @property
    def rendered_sections(self) -> dict[NotesSection, str]:
        """
        The sections the block shows, in order: the progress section only for a branch.
        """
        return {
            section: self.sections.get(section, "")
            for section in NotesSection
            if section is not NotesSection.BRANCH_PROGRESS or self.branch
        }

    def header(self) -> str:
        """
        :return: The instructions the block opens with, every command and option in
            them named as the commands take them.
        :raises KeyError: If the header names a command, or an argument of one, that
            does not exist.
        """
        filled = Placeholder.fill(
            WorkflowTemplate.NOTES_HEADER.read_text(),
            {
                NotesHeaderPlaceholder.SOURCE_OF_NOTES: self.source,
                NotesHeaderPlaceholder.SAVE_COMMAND: self.save_command,
                NotesHeaderPlaceholder.WORKFLOW_COMMAND: self.workflow_command,
                NotesHeaderPlaceholder.COMMANDS: ", ".join(WorkflowCommand),
                NotesHeaderPlaceholder.FINDING_GUIDE: self.finding_guide,
                NotesHeaderPlaceholder.IDEAS_CATEGORY: DefaultDiscussionCategory.IDEAS,
                NotesHeaderPlaceholder.REFUSAL_HINT: RefusalAdvice.hint(),
                NotesHeaderPlaceholder.CO_AUTHOR_TRAILER: Attribution.CO_AUTHOR_TRAILER,
                NotesHeaderPlaceholder.ACKNOWLEDGEMENT: Attribution.ACKNOWLEDGEMENT,
            },
        )
        return (
            CommandReference.pattern()
            .sub(
                lambda found: CommandReference.from_match(found).text(
                    self.workflow_command
                ),
                filled,
            )
            .rstrip("\n")
        )

    def render(self) -> str:
        """:return: The block, markers included."""
        lines = [
            BlockMarker.START,
            self.header(),
            BlockRecord.BRANCH.line(self.branch),
            BlockRecord.LOADED.line(self.digest(self.rendered_sections)),
        ]
        for section, text in self.rendered_sections.items():
            title = (
                f"{section} ({self.branch})"
                if section is NotesSection.BRANCH_PROGRESS
                else section
            )
            lines += [
                "",
                f"## {title}",
                section.start_marker,
                text,
                section.end_marker,
            ]
        lines.append(BlockMarker.END)
        return "\n".join(lines) + "\n"

    def written_into(self, document: str) -> str:
        """
        :param document: ``CLAUDE.local.md`` as it is now, empty when it does not exist.
        :return: It with this block in place of the old one, or appended when it holds
            none; everything outside the block unchanged.
        """
        start = document.find(BlockMarker.START)
        end = document.find(BlockMarker.END)
        if start == -1 or end == -1:
            separator = "\n" if document.strip() else ""
            return (
                document.rstrip("\n")
                + separator
                + ("\n" if separator else "")
                + self.render()
            )
        after = document[end + len(BlockMarker.END) :].removeprefix("\n")
        return document[:start] + self.render() + after

    @staticmethod
    def holds_block(document: str) -> bool:
        """
        :param document: ``CLAUDE.local.md``'s text.
        :return: Whether it holds a notes block.
        """
        return BlockMarker.START in document and BlockMarker.END in document

    @staticmethod
    def read_sections(document: str) -> dict[NotesSection, str]:
        """
        :param document: ``CLAUDE.local.md``'s text.
        :return: The text between each section's markers, for every section it holds.
        """
        sections = {}
        for section in NotesSection:
            start = document.find(section.start_marker)
            end = document.find(section.end_marker)
            if start == -1 or end == -1:
                continue
            sections[section] = document[
                start + len(section.start_marker) : end
            ].strip()
        return sections

    @staticmethod
    def digest(sections: dict[NotesSection, str]) -> str:
        """
        :param sections: The text of each section.
        :return: A digest that differs whenever a section's text, leading and trailing
            whitespace aside, does.
        """
        texts = {section.name: text.strip() for section, text in sections.items()}
        return hashlib.sha256(json.dumps(texts, sort_keys=True).encode()).hexdigest()

    @classmethod
    def holds_unsaved_edits(cls, document: str) -> bool:
        """
        :param document: ``CLAUDE.local.md``'s text.
        :return: Whether its block was edited since it was loaded or last saved.
        """
        loaded = BlockRecord.LOADED.read(document)
        if not cls.holds_block(document) or loaded is None:
            return False
        return loaded != cls.digest(cls.read_sections(document))

    @classmethod
    def marked_saved(cls, document: str) -> str:
        """
        :param document: ``CLAUDE.local.md``'s text, its block just saved.
        :return: It, recording its sections as saved.
        """
        loaded = BlockRecord.LOADED.read(document)
        if loaded is None:
            return document
        return document.replace(
            BlockRecord.LOADED.line(loaded),
            BlockRecord.LOADED.line(cls.digest(cls.read_sections(document))),
        )
