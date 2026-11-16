"""
Tests for :mod:`github_workflow.pull_request_description`: a pull request's description
leads with why it matters, copied from its findings, folds what it changes away, and
names the issues it addresses in lines only the workflow writes.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from github_workflow.command_line import CommandOption
from github_workflow.exceptions import (
    AddressedIssueLineError,
    IssueNamedTwiceError,
    MissingWhyError,
)
from github_workflow.findings import FindingStage, Priority
from github_workflow.pull_request_description import (
    AddressedIssue,
    AddressedIssueNumber,
    DescriptionChange,
    IssueRelation,
    PersonCommandEnding,
    PullRequestDescription,
)

from github_workflow.why_it_matters import WhyItMattersSection
from .issues_in_memory import IssuesInMemory, build_finding, finding_why_section
from .scratch_github import ScratchGitHub

# %% the issues addressed


def test_the_lines_naming_the_issues_are_read_back() -> None:
    named = (
        AddressedIssueNumber(3, IssueRelation.FIXES),
        AddressedIssueNumber(5, IssueRelation.FIXES_IN_PART),
    )

    text = "What it does.\n\n" + "\n".join(issue.reference_line for issue in named)

    assert AddressedIssueNumber.from_description(text) == named


@pytest.mark.parametrize("relation", list(IssueRelation))
def test_a_session_s_text_naming_an_addressed_issue_is_refused(
    relation: IssueRelation,
) -> None:
    line = relation.write_reference_line(3)

    with pytest.raises(AddressedIssueLineError):
        AddressedIssueNumber.refuse_reference_lines(
            f"What it does.\n\n{line}\n", CommandOption.BODY_FILE
        )


# %% the findings


def findings_board() -> IssuesInMemory:
    """:return: Finding 3, with a why, and finding 5, written before findings had
    one."""
    three = build_finding(3, FindingStage.ACCEPTED, Priority.HIGH)
    five = build_finding(5, FindingStage.ACCEPTED, Priority.LOW)
    return IssuesInMemory(
        {
            3: replace(
                three,
                body=finding_why_section().place_into_issue_text("What was found."),
            ),
            5: five,
        }
    )


def addressed_issue(number: int, relation: IssueRelation) -> AddressedIssue:
    """
    :param number: An issue on :func:`findings_board`.
    :param relation: How the pull request addresses it.
    :return: It, as GitHub has it.
    """
    return AddressedIssueNumber(number, relation).read_issue(findings_board())


def description_fixing_three() -> PullRequestDescription:
    """:return: The description of a pull request fixing finding 3."""
    return PullRequestDescription(
        "Records the goals before a restart.",
        addressed_issues=(addressed_issue(3, IssueRelation.FIXES),),
    )


# %% writing it


def test_a_fixed_finding_s_why_is_copied_ahead_of_what_changes() -> None:
    markdown = description_fixing_three().to_markdown(ScratchGitHub.owned)

    assert markdown.index(finding_why_section().explanation) < markdown.index(
        "Records the goals before a restart."
    )


def test_what_changes_is_folded_away() -> None:
    markdown = description_fixing_three().to_markdown(ScratchGitHub.owned)

    folded = markdown[markdown.index("<details>") : markdown.index("</details>")]
    assert "Records the goals before a restart." in folded


def test_a_finding_is_linked_on_the_pull_request_s_repository() -> None:
    markdown = description_fixing_three().to_markdown(ScratchGitHub.owned)

    assert f"({ScratchGitHub.owned.issue_url(3)})" in markdown


def test_the_description_ends_with_the_lines_naming_the_issues() -> None:
    issues = (
        addressed_issue(3, IssueRelation.FIXES),
        addressed_issue(5, IssueRelation.FIXES_IN_PART),
    )
    description = replace(description_fixing_three(), addressed_issues=issues)

    markdown = description.to_markdown(ScratchGitHub.owned)

    assert markdown.rstrip().splitlines()[-2:] == [
        issue.reference_line for issue in issues
    ]


def test_a_bare_issue_number_names_the_pull_request_s_repository() -> None:
    description = replace(description_fixing_three(), change_details="Builds on #2.")

    markdown = description.to_markdown(ScratchGitHub.owned)

    assert f"Builds on {ScratchGitHub.owned.full_name}#2." in markdown


def test_a_finding_without_a_why_is_named_by_its_title() -> None:
    five = addressed_issue(5, IssueRelation.FIXES)
    description = PullRequestDescription("A change.", addressed_issues=(five,))

    markdown = description.to_markdown(ScratchGitHub.owned)

    assert five.issue.title in markdown


def test_a_description_saying_nowhere_why_it_matters_is_refused() -> None:
    with pytest.raises(MissingWhyError):
        PullRequestDescription("A change.").to_markdown(ScratchGitHub.owned)


def test_the_session_s_own_why_leads_the_description() -> None:
    description = replace(
        description_fixing_three(),
        why_it_matters=WhyItMattersSection("Robots stop on restart."),
    )

    markdown = description.to_markdown(ScratchGitHub.owned)

    assert markdown.index("Robots stop on restart.") < markdown.index(
        finding_why_section().explanation
    )


# %% reading it back


def test_a_written_description_is_read_back_as_it_was_given() -> None:
    description = PullRequestDescription(
        "Records the goals.",
        WhyItMattersSection("Robots stop."),
        (
            addressed_issue(3, IssueRelation.FIXES),
            addressed_issue(5, IssueRelation.FIXES_IN_PART),
        ),
    )

    markdown = description.to_markdown(ScratchGitHub.owned)

    assert PullRequestDescription.from_text(markdown, findings_board()) == description


def test_a_description_the_workflow_did_not_write_is_read_as_its_change_details() -> (
    None
):
    text = f"What it does.\n\n{IssueRelation.FIXES.write_reference_line(3)}\n"

    assert PullRequestDescription.from_text(
        text, findings_board()
    ) == PullRequestDescription(
        "What it does.", addressed_issues=(addressed_issue(3, IssueRelation.FIXES),)
    )


def test_an_older_description_is_read_without_its_command_line() -> None:
    ending = PersonCommandEnding("open it upstream", "upstream fork branch")

    details = PullRequestDescription.read_change_details(
        ending.append_once("What it does.")
    )

    assert details == "What it does."


# %% changing it


def test_a_change_keeps_what_it_leaves_out() -> None:
    description = PullRequestDescription(
        "A change.", WhyItMattersSection("Robots stop.")
    )
    three = AddressedIssueNumber(3, IssueRelation.FIXES)

    changed = description.apply_change(
        DescriptionChange(added_issues=(three,)), findings_board()
    )

    assert changed == replace(
        description, addressed_issues=(three.read_issue(findings_board()),)
    )


def test_an_issue_named_again_takes_its_new_relation() -> None:
    three = AddressedIssueNumber(3, IssueRelation.FIXES_IN_PART)

    changed = description_fixing_three().apply_change(
        DescriptionChange(added_issues=(three,)), findings_board()
    )

    assert changed.addressed_issues == (three.read_issue(findings_board()),)


def test_a_dropped_issue_is_no_longer_addressed() -> None:
    changed = description_fixing_three().apply_change(
        DescriptionChange(dropped_issues=(3,)), findings_board()
    )

    assert changed.addressed_issues == ()


def test_an_issue_named_twice_in_one_change_is_refused() -> None:
    three = AddressedIssueNumber(3, IssueRelation.FIXES)

    with pytest.raises(IssueNamedTwiceError):
        description_fixing_three().apply_change(
            DescriptionChange(added_issues=(three,), dropped_issues=(3,)),
            findings_board(),
        )
