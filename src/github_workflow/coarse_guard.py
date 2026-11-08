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

from domain_model.claude_code.hooks import HookInput, ToolCallDenial, ToolKind
from domain_model.git.reading import GitConfigurationLocation
from domain_model.programs import Program

from github_workflow.report_lines import Speaker

# %% the coarse guard


@dataclass(frozen=True)
class CoarseGuard:
    """
    The decision over one tool call while the guard cannot run.
    """

    call: HookInput
    """
    The tool call.
    """

    guard_failure: str
    """
    Why the guard could not run, as the denial names it.
    """

    def denied_reach(self) -> str | None:
        """
        :return: What the call could reach that the guard would have judged, ``None``
            when it reaches neither git nor GitHub.
        """
        match self.call.kind:
            case ToolKind.BASH if Program.any_named(self.call.command):
                return f"a command naming one of {', '.join(Program)}"
            case ToolKind.FILE_WRITE if GitConfigurationLocation.holds(
                PurePath(self.call.file_path)
            ):
                return "a write to git's configuration or hooks"
            case ToolKind.GITHUB:
                return "a GitHub tool"
        return None

    def output(self) -> dict[str, Any] | None:
        """
        :return: The hook's output denying the call, ``None`` to leave it to the usual
            permissions.
        """
        reach = self.denied_reach()
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
    output = CoarseGuard(
        HookInput.from_json(json.load(sys.stdin)), guard_failure
    ).output()
    if output is not None:
        print(json.dumps(output))
