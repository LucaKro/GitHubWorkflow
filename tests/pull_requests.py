"""
Pull requests as the repository client reads them, built for the stand-ins in tests.
"""

from __future__ import annotations

from basstler_domain_model.github.rest_models import PullRequestHead, RestPullRequest
from basstler_domain_model.github.review_models import Author
from basstler_domain_model.github.vocabulary import MergeableState, PullRequestState

REPOSITORY = "LucaKro/project"
"""
The full name of the repository the pull requests here are on.
"""

# %% building a pull request


def pull_request(
    number: int,
    branch: str,
    commit: str = "0" * 40,
    state: PullRequestState = PullRequestState.OPEN,
    repository: str | None = REPOSITORY,
    *,
    title: str | None = None,
    base: str = "main",
    draft: bool = False,
    mergeable_state: MergeableState | None = None,
) -> RestPullRequest:
    """
    :param number: The pull request.
    :param branch: The branch it merges.
    :param commit: The commit its head is at.
    :param state: Whether it is open.
    :param repository: The repository its head is in, ``None`` when deleted.
    :param title: Its title, ``Pull request <number>`` when ``None``.
    :param base: The branch it targets.
    :param draft: Whether it is a draft.
    :param mergeable_state: GitHub's verdict on merging it.
    :return: The pull request as GitHub lists it.
    """
    return RestPullRequest(
        number=number,
        title=f"Pull request {number}" if title is None else title,
        body=None,
        url=f"https://github.com/{REPOSITORY}/pull/{number}",
        state=state,
        merged=False,
        draft=draft,
        head=PullRequestHead(branch, repository, commit, Author("LucaKro")),
        base=base,
        labels=(),
        mergeable_state=mergeable_state,
    )
