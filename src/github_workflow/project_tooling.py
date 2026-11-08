"""
What a session is told about the tool a project manages its Python environment with.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from basstler_domain_model.python_project import EnvironmentTool, UvTool

from github_workflow.command_line import CommandOption
from github_workflow.report_lines import Audience, ReportLine, Speaker, Tone

# %% the tool managing the project's environment


@dataclass(frozen=True)
class ProjectTooling:
    """
    What a session is told about the tool the project manages its environment with:
    to set the environment up with it whenever tests need it, never by hand. The
    workflow never runs the tool itself.
    """

    root: Path
    """
    The project's root.
    """

    tools: tuple[EnvironmentTool, ...] = (UvTool(),)
    """
    The tools looked for, in order; the first the project declares counts.
    """

    def lines(self) -> list[ReportLine]:
        """
        :return: How to set the environment up, or that the tool is missing; nothing
            when the project declares none of the tools.
        """
        tool = next((tool for tool in self.tools if tool.manages(self.root)), None)
        if tool is None:
            return []
        command = tool.setup_command(self.root)
        if shutil.which(tool.executable) is None:
            return [
                ReportLine(
                    Speaker.WORKFLOW.says(
                        f"this project's environment is managed with "
                        f"{tool.executable}, which is not installed, so `{command}` "
                        f"cannot set it up: ask the person whether to install it, and "
                        f"install none of the project's packages by hand"
                    ),
                    Tone.ACTION,
                )
            ]
        return [
            ReportLine(
                Speaker.WORKFLOW.says(
                    f"this project's environment is managed with {tool.executable}: "
                    f"whenever tests need it, set it up with `{command}` and run them "
                    f"in it, giving the workflow's proof commands its interpreter with "
                    f"`{CommandOption.PYTHON}`; never install the project's packages "
                    f"by hand"
                ),
                Tone.NEWS,
                Audience.MODEL,
            )
        ]
