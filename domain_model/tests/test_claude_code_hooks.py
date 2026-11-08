"""
Tests for :mod:`basstler_domain_model.claude_code.hooks`: what Claude Code hands a hook
and what the hook answers.
"""

from __future__ import annotations

import pytest

from basstler_domain_model.claude_code.hooks import (
    FileWritingTool,
    HookInput,
    HookKey,
    HookValue,
    ToolCallDenial,
    ToolKind,
)

# %% the tool call


def test_a_bash_call_is_read_with_its_command_line():
    call = HookInput.from_json(
        {
            HookKey.TOOL_NAME: HookValue.BASH_TOOL,
            HookKey.TOOL_INPUT: {HookKey.COMMAND: "git log"},
        }
    )

    assert (call.kind, call.command) == (ToolKind.BASH, "git log")


@pytest.mark.parametrize("tool", list(FileWritingTool))
def test_a_file_writing_call_is_read_with_its_file(tool: FileWritingTool):
    call = HookInput.from_json(
        {HookKey.TOOL_NAME: tool, HookKey.TOOL_INPUT: {HookKey.FILE_PATH: "/a/file"}}
    )

    assert (call.kind, call.file_path) == (ToolKind.FILE_WRITE, "/a/file")


def test_a_github_mcp_tool_is_named_without_its_server():
    call = HookInput(f"{HookValue.MCP_TOOL_PREFIX}github__get_issue")

    assert (call.kind, call.tool_without_server) == (ToolKind.GITHUB, "get_issue")


def test_another_tool_is_neither():
    assert HookInput("Read").kind is ToolKind.OTHER


# %% the answer


def test_a_denial_answers_the_pre_tool_use_event():
    answer = ToolCallDenial("why").answer()

    assert answer == {
        HookKey.HOOK_SPECIFIC_OUTPUT: {
            HookKey.HOOK_EVENT_NAME: HookValue.PRE_TOOL_USE,
            HookKey.PERMISSION_DECISION: HookValue.DENY,
            HookKey.PERMISSION_DECISION_REASON: "why",
        }
    }


def test_a_denial_shown_to_the_person_carries_the_message():
    assert ToolCallDenial("why", "shown").answer()[HookKey.SYSTEM_MESSAGE] == "shown"
