"""
Pull requests as the repository client reads them, built for the stand-ins in tests.
"""

from __future__ import annotations

from domain_model.github.rest_models import PullRequestHead, RestPullRequest
from domain_model.github.review_models import Author
from domain_model.github.vocabulary import MergeableState, PullRequestState

from .repositories_by_owner import RepositoriesByOwner
from .scratch_github import ScratchGitHub

# %% building a pull request


def pull_request(
    number: int,
    branch: str,
    commit: str = "0" * 40,
    state: PullRequestState = PullRequestState.OPEN,
    repository: str | None = ScratchGitHub.owned.full_name,
    *,
    title: str | None = None,
    base: str = RepositoriesByOwner.default_branch,
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
        url=ScratchGitHub.owned.pull_request_url(number),
        state=state,
        merged=False,
        draft=draft,
        head=PullRequestHead(
            branch, repository, commit, Author(ScratchGitHub.owned.owner)
        ),
        base=base,
        labels=(),
        mergeable_state=mergeable_state,
    )
