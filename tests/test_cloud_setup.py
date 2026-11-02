"""
Tests for :mod:`github_workflow.cloud_setup`: a cloud session's user settings get the
plugin's hooks and the workflow's permission, once, next to what they held.
"""

from __future__ import annotations

import json
from pathlib import Path

from github_workflow.cloud_setup import CloudSettings, ClaudeSettingsKey, PluginFile
from github_workflow.command_line import WorkflowCommand

PLUGIN = Path(__file__).parents[1] / "plugin"
"""
The plugin whose hooks are merged in.
"""

# %% merging


def test_the_plugin_s_hooks_run_from_where_the_plugin_is(tmp_path: Path):
    settings = CloudSettings(tmp_path / "settings.json", PLUGIN).merged({})

    hooks = json.dumps(settings[ClaudeSettingsKey.HOOKS])
    assert PluginFile.ROOT_VARIABLE not in hooks
    assert str(PLUGIN / "hooks" / "guard.sh") in hooks


def test_the_workflow_s_commands_may_run_without_asking(tmp_path: Path):
    settings = CloudSettings(tmp_path / "settings.json", PLUGIN).merged({})

    allowed = settings[ClaudeSettingsKey.PERMISSIONS][ClaudeSettingsKey.ALLOW]
    assert allowed == [f"Bash({WorkflowCommand.command_line()}:*)"]


def test_writing_twice_adds_nothing_the_second_time(tmp_path: Path):
    path = tmp_path / ".claude" / "settings.json"
    CloudSettings(path, PLUGIN).write()
    once = path.read_text()

    CloudSettings(path, PLUGIN).write()

    assert path.read_text() == once


def test_settings_already_there_are_kept(tmp_path: Path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"theme": "dark"}))

    CloudSettings(path, PLUGIN).write()

    assert json.loads(path.read_text())["theme"] == "dark"
