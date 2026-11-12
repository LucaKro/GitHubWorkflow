"""
Replays an upstream review answer the answering module recorded, and prints the review
state it reads back as the probe writes it out. Temporary, for the review-read
comparison.

Usage: ``python replay.py <request.json> <answer.json>``
"""

from __future__ import annotations

import sys
from pathlib import Path

from domain_model.github.clients import RecordedAnswers, ReplayingGraphQLClient

from github_workflow.probe.library_check import PullRequestReviewStateCall
from github_workflow.upstream_reviews import UpstreamReviewRequest

# %% replaying


def main() -> None:
    """
    Read the request and its answer the command line names, and print what replaying the
    answer reads.
    """
    request_file, answer_file = sys.argv[1:]
    request = UpstreamReviewRequest.from_file(Path(request_file))
    answers = RecordedAnswers.from_json(Path(answer_file).read_text())
    snapshot = request.snapshot(ReplayingGraphQLClient(answers))
    print(PullRequestReviewStateCall().snapshot_text(snapshot))


if __name__ == "__main__":
    main()
