"""
Tests for :mod:`domain_model.claude_code.hooks`: what Claude Code hands a hook and what
the hook answers.
"""

from __future__ import annotations

import pytest

from domain_model.claude_code.hooks import (
    FileWriteCall,
    FileWritingTool,
    GitHubToolCall,
    HookKey,
    HookValue,
    OtherToolCall,
    ShellCommandCall,
    ToolCall,
    ToolCallDenial,
)

# %% the tool call


def test_a_bash_call_is_read_with_its_command_line():
    call = ToolCall.from_json(
        {
            HookKey.TOOL_NAME: HookValue.BASH_TOOL,
            HookKey.TOOL_INPUT: {HookKey.COMMAND: "git log"},
        }
    )

    assert call == ShellCommandCall(HookValue.BASH_TOOL, "git log")


@pytest.mark.parametrize("tool", list(FileWritingTool))
def test_a_file_writing_call_is_read_with_its_file(tool: FileWritingTool):
    call = ToolCall.from_json(
        {HookKey.TOOL_NAME: tool, HookKey.TOOL_INPUT: {HookKey.FILE_PATH: "/a/file"}}
    )

    assert call == FileWriteCall(tool, "/a/file")


def test_a_github_mcp_tool_is_named_without_its_server():
    call = ToolCall.from_json(
        {HookKey.TOOL_NAME: f"{HookValue.MCP_TOOL_PREFIX}github__get_issue"}
    )

    assert (type(call), call.tool_without_server) == (GitHubToolCall, "get_issue")


def test_another_tool_is_neither():
    assert ToolCall.from_json({HookKey.TOOL_NAME: "Read"}) == OtherToolCall("Read")


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
