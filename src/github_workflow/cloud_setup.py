"""
Give a Claude Code cloud session the workflow's hooks, which it cannot load as a plugin:
the plugin's hooks are merged into the session's user settings, with the rule letting
the workflow's commands run without asking.

Usage: ``python -m github_workflow.cloud_setup <plugin directory>``, run with the
runtime's interpreter.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from github_workflow.command_line import WorkflowCommand

# %% vocabulary


class ClaudeSettingsKey(StrEnum):
    """
    The keys of Claude Code's settings file the setup writes.
    """

    HOOKS = "hooks"
    PERMISSIONS = "permissions"
    ALLOW = "allow"


class PluginFile(StrEnum):
    """
    The plugin's files the setup reads, and the variable they name the plugin's
    directory by.
    """

    HOOKS = "hooks/hooks.json"
    """
    The plugin's hooks.
    """

    ROOT_VARIABLE = "${CLAUDE_PLUGIN_ROOT}"
    """
    How a plugin's hook commands name the plugin's directory.
    """


# %% the settings


@dataclass(frozen=True)
class CloudSettings:
    """
    A cloud session's user settings, given the workflow's hooks and permission.
    """

    path: Path
    """
    The settings file.
    """

    plugin: Path
    """
    The plugin's directory, whose hooks are merged in.
    """

    def merged(self, settings: dict[str, Any]) -> dict[str, Any]:
        """
        :param settings: The settings as they are.
        :return: Them with the plugin's hooks and the workflow's permission, each added
            once however often this runs.
        """
        hooks_file = self.plugin / PluginFile.HOOKS
        plugin_hooks = json.loads(
            hooks_file.read_text().replace(PluginFile.ROOT_VARIABLE, str(self.plugin))
        )[ClaudeSettingsKey.HOOKS]
        hooks = settings.setdefault(ClaudeSettingsKey.HOOKS, {})
        for event, entries in plugin_hooks.items():
            present = hooks.setdefault(event, [])
            present += [entry for entry in entries if entry not in present]
        allowed = settings.setdefault(ClaudeSettingsKey.PERMISSIONS, {}).setdefault(
            ClaudeSettingsKey.ALLOW, []
        )
        rule = f"Bash({WorkflowCommand.command_line()}:*)"
        if rule not in allowed:
            allowed.append(rule)
        return settings

    def write(self) -> None:
        """
        Merge the hooks and the permission into the settings file, creating it when
        there is none.
        """
        existing = json.loads(self.path.read_text()) if self.path.exists() else {}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.merged(existing), indent=2) + "\n")


# %% entry point


def main() -> None:
    """
    Merge the plugin the command line names into the user settings.
    """
    settings = CloudSettings(
        Path.home() / ".claude" / "settings.json", Path(sys.argv[1])
    )
    settings.write()
    print(f"github-workflow: hooks and permission written to {settings.path}")


if __name__ == "__main__":
    main()
