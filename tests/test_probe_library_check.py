"""
Tests for :mod:`github_workflow.probe.library_check`: the review state written out as a
text two reads of one pull request can be compared by.
"""

from __future__ import annotations

import json

from domain_model.github.pull_request_models import UpstreamPullRequestSnapshot
from domain_model.github.review_models import Author, Review
from domain_model.github.vocabulary import ReviewState

from github_workflow.probe.library_check import PullRequestReviewStateCall

from .test_own_pull_request import thread

# %% the review state as text


def test_the_review_state_names_each_review_thread_and_comment_on_a_line() -> None:
    review = Review(
        Author("a-reviewer"), ReviewState.APPROVED, "Fine.\nShip it.", "2026-11-04"
    )
    listed = thread(7, resolved=True)
    [comment] = listed.comments
    snapshot = UpstreamPullRequestSnapshot(
        3, "A title", "https://pull", [review], [listed], None
    )

    text = PullRequestReviewStateCall().snapshot_text(snapshot)

    assert text.splitlines() == [
        "checks not reported",
        f"review a-reviewer {ReviewState.APPROVED} 2026-11-04 {json.dumps(review.body)}",
        f"thread {listed.path}:{listed.line} resolved True outdated False",
        f"  comment a-reviewer {comment.created_at} {json.dumps(comment.body)}",
    ]
