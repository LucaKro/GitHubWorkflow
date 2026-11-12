"""
Tests for :mod:`domain_model.github.vocabulary`: reading GitHub's fixed values, and what
each one means.
"""

from __future__ import annotations

import json

import pytest

from domain_model.github.exceptions import (
    NoCheckOutcomesError,
    UnrecognisedGitHubValueError,
)
from domain_model.github.pull_request_models import CheckResult
from domain_model.github.vocabulary import (
    CheckOutcome,
    MergeableState,
    PullRequestState,
    RestJSONKey,
    RollupState,
)

from .dataset.locations import DatasetLocation

# %% values GitHub added later


def test_an_unrecognised_check_conclusion_is_refused_naming_it() -> None:
    node = json.loads(DatasetLocation.CHECK_RUN_UNRECOGNISED_CONCLUSION.read_text())

    with pytest.raises(UnrecognisedGitHubValueError) as raised:
        CheckResult.from_check_run_json(node)

    assert (raised.value.vocabulary, raised.value.value) == (
        CheckOutcome,
        node[RestJSONKey.CONCLUSION].upper(),
    )


def test_an_unrecognised_value_is_refused_naming_it() -> None:
    with pytest.raises(UnrecognisedGitHubValueError) as raised:
        PullRequestState.from_value("archived")

    assert (raised.value.vocabulary, raised.value.value) == (
        PullRequestState,
        "archived",
    )


def test_a_recognised_name_reads_as_its_member() -> None:
    assert PullRequestState.from_name(PullRequestState.MERGED.name) is (
        PullRequestState.MERGED
    )


def test_a_recognised_value_reads_as_its_member() -> None:
    assert PullRequestState.from_value(PullRequestState.CLOSED.value) is (
        PullRequestState.CLOSED
    )


# %% conflicts


@pytest.mark.parametrize(
    ("state", "conflicts"),
    [
        (MergeableState.DIRTY, True),
        (MergeableState.UNKNOWN, None),
        (MergeableState.DRAFT, None),
        (MergeableState.CLEAN, False),
        (MergeableState.UNSTABLE, False),
        (MergeableState.BLOCKED, False),
        (MergeableState.BEHIND, False),
        (MergeableState.HAS_HOOKS, False),
    ],
)
def test_only_a_computed_state_says_whether_a_branch_conflicts(
    state: MergeableState, conflicts: bool | None
) -> None:
    assert state.conflicts is conflicts


# %% rolling checks up


@pytest.mark.parametrize(
    ("outcome", "verdict"),
    [
        (CheckOutcome.SUCCESS, RollupState.SUCCESS),
        (CheckOutcome.NEUTRAL, RollupState.SUCCESS),
        (CheckOutcome.SKIPPED, RollupState.SUCCESS),
        (CheckOutcome.ERROR, RollupState.ERROR),
        (CheckOutcome.PENDING, RollupState.PENDING),
        (CheckOutcome.EXPECTED, RollupState.EXPECTED),
        (CheckOutcome.FAILURE, RollupState.FAILURE),
        (CheckOutcome.CANCELLED, RollupState.FAILURE),
        (CheckOutcome.TIMED_OUT, RollupState.FAILURE),
        (CheckOutcome.ACTION_REQUIRED, RollupState.FAILURE),
        (CheckOutcome.STALE, RollupState.FAILURE),
        (CheckOutcome.STARTUP_FAILURE, RollupState.FAILURE),
    ],
)
def test_each_outcome_rolls_up_to_its_verdict(
    outcome: CheckOutcome, verdict: RollupState
) -> None:
    assert outcome.rolls_up_to is verdict


def test_the_rollup_is_the_worst_verdict_any_check_gives() -> None:
    outcomes = [CheckOutcome.SUCCESS, CheckOutcome.PENDING, CheckOutcome.ERROR]

    assert RollupState.from_outcomes(outcomes) is RollupState.ERROR


def test_a_rollup_over_no_outcomes_is_refused() -> None:
    with pytest.raises(NoCheckOutcomesError):
        RollupState.from_outcomes([])
