"""
Tests for :mod:`github_workflow.pull_request_description`: a pull request's description
leads with why it matters, copied from its findings, folds what it changes away, and
names the issues it addresses in lines only the workflow writes.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from domain_model.github.vocabulary import ClosingKeyword

from github_workflow.command_line import CommandOption
from github_workflow.exceptions import (
    AddressedIssueLineError,
    IssueNamedTwiceError,
    MissingWhyError,
)
from github_workflow.findings import FindingStage, Priority
from github_workflow.pull_request_description import (
    AddressedIssues,
    DescriptionChange,
    PersonCommandEnding,
    PullRequestDescription,
)

from .issues_in_memory import IssuesInMemory, build_finding, finding_why
from .scratch_github import ScratchGitHub

# %% the issues addressed


def test_the_lines_naming_the_issues_are_read_back() -> None:
    addressed = AddressedIssues((3, 4), (5,))

    text = "What it does.\n\n" + "\n".join(addressed.lines())

    assert AddressedIssues.from_description(text) == addressed


def test_an_issue_named_again_moves_to_the_list_it_is_named_in() -> None:
    addressed = AddressedIssues((3,), (5,))

    assert addressed.changed([5], [3], []) == AddressedIssues((5,), (3,))


def test_a_dropped_issue_is_no_longer_addressed() -> None:
    addressed = AddressedIssues((3, 4), (5,))

    assert addressed.changed([], [], [4, 5]) == AddressedIssues((3,), ())


def test_an_issue_named_twice_in_one_change_is_refused() -> None:
    with pytest.raises(IssueNamedTwiceError):
        AddressedIssues().changed([3], [], [3])


@pytest.mark.parametrize(
    "line",
    [ClosingKeyword.FIXES.reference(3), f"{AddressedIssues.partial_fix_words} #3"],
    ids=["fixed", "fixed in part"],
)
def test_a_session_s_text_naming_an_addressed_issue_is_refused(line: str) -> None:
    with pytest.raises(AddressedIssueLineError):
        AddressedIssues.refuse_lines(
            f"What it does.\n\n{line}\n", CommandOption.BODY_FILE
        )


# %% rendering


def findings_board() -> IssuesInMemory:
    """:return: Finding 3, with a why, and finding 5, written before findings had
    one."""
    three = build_finding(3, FindingStage.ACCEPTED, Priority.HIGH)
    five = build_finding(5, FindingStage.ACCEPTED, Priority.LOW)
    return IssuesInMemory(
        {3: replace(three, body=finding_why().place("What was found.")), 5: five}
    )


def fixing_three() -> PullRequestDescription:
    """:return: The description of a pull request fixing finding 3."""
    return PullRequestDescription(
        "Records the goals before a restart.", addressed=AddressedIssues((3,))
    )


def test_a_fixed_finding_s_why_is_copied_ahead_of_what_changes() -> None:
    rendered = fixing_three().render(findings_board(), ScratchGitHub.owned)

    assert rendered.index(finding_why().text) < rendered.index(
        "Records the goals before a restart."
    )


def test_what_changes_is_folded_away() -> None:
    rendered = fixing_three().render(findings_board(), ScratchGitHub.owned)

    folded = rendered[rendered.index("<details>") : rendered.index("</details>")]
    assert "Records the goals before a restart." in folded


def test_a_finding_is_linked_on_the_pull_request_s_repository() -> None:
    rendered = fixing_three().render(findings_board(), ScratchGitHub.owned)

    assert f"({ScratchGitHub.owned.issue_url(3)})" in rendered


def test_the_description_ends_with_the_lines_naming_the_issues() -> None:
    description = replace(fixing_three(), addressed=AddressedIssues((3,), (5,)))

    rendered = description.render(findings_board(), ScratchGitHub.owned)

    assert rendered.rstrip().splitlines()[-2:] == description.addressed.lines()


def test_a_bare_issue_number_names_the_pull_request_s_repository() -> None:
    description = replace(fixing_three(), changes="Builds on #2.")

    rendered = description.render(findings_board(), ScratchGitHub.owned)

    assert f"Builds on {ScratchGitHub.owned.full_name}#2." in rendered


def test_a_finding_without_a_why_is_named_by_its_title() -> None:
    description = PullRequestDescription("A change.", addressed=AddressedIssues((5,)))

    rendered = description.render(findings_board(), ScratchGitHub.owned)

    assert findings_board().issue(5).title in rendered


def test_a_description_saying_nowhere_why_it_matters_is_refused() -> None:
    with pytest.raises(MissingWhyError):
        PullRequestDescription("A change.").render(
            findings_board(), ScratchGitHub.owned
        )


def test_the_session_s_own_why_leads_the_description() -> None:
    description = replace(fixing_three(), why="Robots stop on every restart.")

    rendered = description.render(findings_board(), ScratchGitHub.owned)

    assert rendered.index("Robots stop on every restart.") < rendered.index(
        finding_why().text
    )


# %% reading it back


def test_a_rendered_description_is_read_back_as_it_was_given() -> None:
    description = PullRequestDescription(
        "Records the goals.", "Robots stop.", AddressedIssues((3,), (5,))
    )

    rendered = description.render(findings_board(), ScratchGitHub.owned)

    assert PullRequestDescription.from_text(rendered) == description


def test_a_description_the_workflow_did_not_write_is_read_as_its_changes() -> None:
    text = f"What it does.\n\n{ClosingKeyword.FIXES.reference(3)}\n"

    assert PullRequestDescription.from_text(text) == PullRequestDescription(
        "What it does.", addressed=AddressedIssues((3,))
    )


def test_an_older_description_is_read_without_its_command_line() -> None:
    ending = PersonCommandEnding("open it upstream", "upstream fork branch")

    read = PullRequestDescription.from_text(ending.append_once("What it does."))

    assert read.changes == "What it does."


def test_a_change_keeps_what_it_leaves_out() -> None:
    description = PullRequestDescription("A change.", "Robots stop.")

    changed = description.changed(DescriptionChange(fixed=(3,)))

    assert changed == replace(description, addressed=AddressedIssues((3,)))
