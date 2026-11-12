"""
The guard's stand-in while the guard itself cannot run: it denies every call that could
reach git or GitHub and lets every other call run. Runs on the standard library and the
plugin's own source alone.

Usage: ``python3 -I -c 'import sys; sys.path[:0] = sys.argv[1].split(":"); from
github_workflow.coarse_guard import main; main(sys.argv[2])' <source directories>
<guard failure> < hook-input.json``
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any

from domain_model.claude_code.hooks import (
    FileWriteCall,
    GitHubToolCall,
    OtherToolCall,
    ShellCommandCall,
    ToolCall,
    ToolCallDenial,
    ToolCallJudge,
)
from domain_model.git.reading import GitConfigurationLocation
from domain_model.programs import Program

from github_workflow.report_lines import Speaker

# %% the coarse guard


@dataclass(frozen=True)
class CoarseGuard(ToolCallJudge[str | None]):
    """
    The decision over a tool call while the guard cannot run: what the call could reach
    that the guard would have judged, ``None`` when it reaches neither git nor GitHub.
    """

    guard_failure: str
    """
    Why the guard could not run, as the denial names it.
    """

    def decide_shell_command(self, call: ShellCommandCall) -> str | None:
        if Program.any_named(call.command):
            return f"a command naming one of {', '.join(Program)}"
        return None

    def decide_file_write(self, call: FileWriteCall) -> str | None:
        if GitConfigurationLocation.holds(PurePath(call.file_path)):
            return "a write to git's configuration or hooks"
        return None

    def decide_github_tool(self, call: GitHubToolCall) -> str | None:
        return "a GitHub tool"

    def decide_other_tool(self, call: OtherToolCall) -> str | None:
        return None

    def output(self, call: ToolCall) -> dict[str, Any] | None:
        """
        :param call: A tool call.
        :return: The hook's output denying it, ``None`` to leave it to the usual
            permissions.
        """
        reach = call.request_decision(self)
        if reach is None:
            return None
        return ToolCallDenial(
            Speaker.WORKFLOW.says(
                f"the guard could not run ({self.guard_failure}), so {reach} is denied "
                f"until it can; calls reaching neither git nor GitHub still run. Tell "
                f"the person running the tool."
            )
        ).answer()


# %% entry point


def main(guard_failure: str) -> None:
    """
    Read the hook's input and print the coarse guard's decision.

    :param guard_failure: Why the guard could not run.
    """
    output = CoarseGuard(guard_failure).output(ToolCall.from_json(json.load(sys.stdin)))
    if output is not None:
        print(json.dumps(output))
