"""
The lines the workflow reports, to the person in the terminal and to the model, and the
session start's answer made of them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum

from basstler_domain_model.claude_code.hooks import HookKey, HookValue

from github_workflow.install import Distribution

# %% who speaks


class Speaker(StrEnum):
    """
    Who a line shown to the person or given to the model comes from.
    """

    WORKFLOW = Distribution.WORKFLOW.value
    """
    The workflow: its commands, hooks and session start.
    """

    def says(self, text: str) -> str:
        """
        :param text: What is said.
        :return: It, opened by who says it.
        """
        return f"{self}: {text}"


# %% report lines


class Tone(StrEnum):
    """
    How a line of the session start stands out, named for what it means, valued as the
    terminal colour it is shown in.
    """

    NEWS = "36"
    """
    What was loaded or done: cyan.
    """

    ACTION = "33"
    """
    Something for the person to do: yellow.
    """

    PROBLEM = "31"
    """
    Something that failed: red.
    """


class ReportLineKey(StrEnum):
    """
    The keys of a report line handed from one process to another.
    """

    TEXT = "text"
    """
    What the line says.
    """

    TONE = "tone"
    """
    How it stands out, by the tone's name.
    """

    AUDIENCE = "audience"
    """
    Who it is for.
    """

    EMPHASES = "emphases"
    """
    Its emphasised parts, each with its highlight.
    """


class Audience(StrEnum):
    """
    Who a line the session starts with is for.
    """

    EVERYONE = "everyone"
    """
    The person, who sees it in the terminal, and the model.
    """

    MODEL = "model"
    """
    The model alone, such as an instruction on how to work, which the person need
    not read on every prompt.
    """


class Highlight(StrEnum):
    """
    How a part of a line stands out from the rest, valued as its terminal style; none
    is a colour a :class:`Tone` uses, and each reads on dark and light terminals.
    """

    HEADING = "1;94"
    """
    A section's heading: bold bright blue.
    """

    STATUS = "32"
    """
    A pull request's status tags: green.
    """

    CRITICAL = "1;97;45"
    """
    A critical finding's priority tag: bold white on magenta.
    """

    HIGH = "1;95"
    """
    A high finding's priority tag: bold bright magenta.
    """

    MEDIUM = "95"
    """
    A medium finding's priority tag: bright magenta.
    """

    LOW = "2;95"
    """
    A low finding's priority tag: dim bright magenta.
    """


@dataclass(frozen=True)
class Emphasis:
    """
    A part of a line shown in a style of its own.
    """

    part: str
    """
    The part, as it stands in the line's text; its first occurrence is styled.
    """

    highlight: Highlight
    """
    How it stands out.
    """


@dataclass(frozen=True)
class ReportLine:
    """
    One line the session starts with.
    """

    text: str
    """
    What it says.
    """

    tone: Tone
    """
    How it stands out.
    """

    audience: Audience = Audience.EVERYONE
    """
    Who it is for.
    """

    emphases: tuple[Emphasis, ...] = ()
    """
    The parts of it shown in styles of their own.
    """

    @property
    def shown(self) -> str:
        """
        :return: The line in bold, in its tone's colour, its emphasised parts in their
            own styles, as the person sees it.
        """
        line = f"\033[1;{self.tone}m"
        text = self.text
        for emphasis in self.emphases:
            before, found, text = text.partition(emphasis.part)
            line += before
            if found:
                line += f"\033[0;{emphasis.highlight}m{found}\033[0;1;{self.tone}m"
        return f"{line}{text}\033[0m"

    def to_json(self) -> str:
        """:return: The line, for a process that reports to the session start."""
        return json.dumps(
            {
                ReportLineKey.TEXT: self.text,
                ReportLineKey.TONE: self.tone.name,
                ReportLineKey.AUDIENCE: self.audience,
                ReportLineKey.EMPHASES: [
                    [emphasis.part, emphasis.highlight] for emphasis in self.emphases
                ],
            }
        )

    @classmethod
    def from_json(cls, line: str) -> ReportLine:
        """
        :param line: A line as :meth:`to_json` wrote it.
        :return: The line.
        """
        data = json.loads(line)
        return cls(
            data[ReportLineKey.TEXT],
            Tone[data[ReportLineKey.TONE]],
            Audience(data[ReportLineKey.AUDIENCE]),
            tuple(
                Emphasis(part, Highlight(highlight))
                for part, highlight in data[ReportLineKey.EMPHASES]
            ),
        )


@dataclass(frozen=True)
class SessionStartReport:
    """
    What a session starts with: coloured for the person, the lines for everyone only,
    and plain for the model, every line.
    """

    lines: list[ReportLine]
    """
    One line per thing to report.
    """

    event: HookValue = HookValue.SESSION_START
    """
    The hook event the report answers.
    """

    def to_json(self) -> str:
        """:return: The hook's output."""
        return json.dumps(
            {
                HookKey.SYSTEM_MESSAGE: "\n".join(
                    line.shown
                    for line in self.lines
                    if line.audience is Audience.EVERYONE
                ),
                HookKey.HOOK_SPECIFIC_OUTPUT: {
                    HookKey.HOOK_EVENT_NAME: self.event,
                    HookKey.ADDITIONAL_CONTEXT: "\n".join(
                        line.text for line in self.lines
                    ),
                },
            }
        )
