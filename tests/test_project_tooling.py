"""
Tests for :mod:`github_workflow.project_tooling`: what a session is told about the tool
a project manages its environment with.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from basstler_domain_model.claude_code.hooks import HookKey
from basstler_domain_model.locations import PythonProjectFile
from basstler_domain_model.python_project import DevelopmentExtra, UvTool

from github_workflow.project_tooling import ProjectTooling
from github_workflow.report_lines import SessionStartReport, Tone
from github_workflow.session_start import SessionStart
from github_workflow.settings import WorkflowSettings

from .repositories_by_owner import RepositoriesByOwner

# %% helpers


def uv_project(root: Path) -> Path:
    """
    :param root: An empty directory.
    :return: It, as a project uv manages, with a development extra and another one.
    """
    (root / PythonProjectFile.UV_LOCK).write_text("version = 1\n")
    (root / PythonProjectFile.PYPROJECT).write_text(
        "[project]\n"
        'name = "project"\n'
        "[project.optional-dependencies]\n"
        f'{DevelopmentExtra.DEV} = ["pytest"]\n'
        'docs = ["sphinx"]\n'
    )
    return root


# %% what a session is told


def test_a_session_is_told_to_set_up_with_the_tool(tmp_path: Path) -> None:
    tool = UvTool(executable=sys.executable)
    root = uv_project(tmp_path)

    [line] = ProjectTooling(root, (tool,)).lines()

    assert f"`{tool.setup_command(root)}`" in line.text
    assert line.tone is Tone.NEWS


def test_the_set_up_instruction_reaches_the_model_alone(tmp_path: Path) -> None:
    tool = UvTool(executable=sys.executable)
    lines = ProjectTooling(uv_project(tmp_path), (tool,)).lines()

    report = json.loads(SessionStartReport(lines).to_json())

    given = report[HookKey.HOOK_SPECIFIC_OUTPUT][HookKey.ADDITIONAL_CONTEXT]
    assert (report[HookKey.SYSTEM_MESSAGE], given) == ("", lines[0].text)


def test_a_missing_tool_is_left_for_the_person(tmp_path: Path) -> None:
    tool = UvTool(executable=str(tmp_path / "no-such-tool"))

    [line] = ProjectTooling(uv_project(tmp_path), (tool,)).lines()

    assert line.tone is Tone.ACTION


def test_a_project_declaring_no_tool_tells_nothing(tmp_path: Path) -> None:
    assert ProjectTooling(tmp_path).lines() == []


def test_a_uv_project_s_session_start_tells_how_to_set_it_up(
    repositories: RepositoriesByOwner, foreign_url: str, settings: WorkflowSettings
) -> None:
    checkout = repositories.clone(foreign_url, "theirs")
    uv_project(checkout.root)

    lines = SessionStart(checkout, settings).report()

    assert ProjectTooling(checkout.root).lines()[0] in lines
