"""
The checks a probe runs, each group answering for one part of the workflow, and each
cleaning up what it created.
"""

from __future__ import annotations

import platform
import sys
from dataclasses import dataclass
from enum import StrEnum

from basstler_domain_model.environment import (
    ClaudeCodeVariable,
    GitHubCredentialVariable,
)
from basstler_domain_model.github.vocabulary import RestJSONKey
from basstler_domain_model.repository import Repository

from github_workflow.probe.commands import CommandRunner
from github_workflow.probe.library_check import LibraryCheck
from github_workflow.probe.rest import (
    HttpMethod,
    RepositoryRoute,
    RestCaller,
    RestResponse,
)
from github_workflow.probe.results import CheckGroup, ProbeReport

# %% vocabulary


class ProbeJSONKey(StrEnum):
    """
    The REST fields the probe reads that the domain model does not read yet.
    """

    DEFAULT_BRANCH = "default_branch"
    HAS_ISSUES = "has_issues"
    STATE_REASON = "state_reason"
    REQUESTED_REVIEWERS = "requested_reviewers"
    AHEAD_BY = "ahead_by"
    BEHIND_BY = "behind_by"
    TOTAL_COUNT = "total_count"
    COLOR = "color"


class IssueState(StrEnum):
    """
    The issue states and close reasons the finding boards use.
    """

    OPEN = "open"
    CLOSED = "closed"
    NOT_PLANNED = "not_planned"
    ALL = "all"


class ProbeText(StrEnum):
    """
    The names and texts the probe creates things with, all marked as the probe's.
    """

    LABEL = "probe-triage"
    LABEL_COLOR = "ededed"
    LABEL_DESCRIPTION = "Temporary, created by the cloud probe"
    ISSUE_TITLE = "Probe: finding board lifecycle"
    ISSUE_BODY = (
        "Created by the cloud probe to test the finding boards; closed by it again."
    )
    REJECTION = "Rejected by the probe: this finding only tests the board."
    PULL_REQUEST_TITLE = "Probe: draft pull request"
    PULL_REQUEST_BODY = "Created by the cloud probe; closed by it again."
    COMMIT_MESSAGE = "Probe commit, never merged"


class BranchName(StrEnum):
    """
    The branch name shapes the probe pushes, each followed by the run's stamp.
    """

    PLAIN = "probe/notes-"
    """
    A name of the workflow's own choosing, as a notes branch would have.
    """

    SESSION_STYLE = "claude/probe-notes-"
    """
    A name in the ``claude/`` namespace cloud sessions push their own branches to.
    """

    PULL_REQUEST = "probe/pull-request-"
    """
    The head of the draft pull request the probe opens.
    """


# %% the probe


@dataclass
class Probe:
    """
    One run of every check against the repository the session works in.
    """

    runner: CommandRunner
    """
    Runs git, curl and the library checks in the checkout.
    """

    caller: RestCaller
    """
    Calls the REST API.
    """

    repository: Repository
    """
    The repository the session works in.
    """

    stamp: str
    """
    What makes this run's branch and issue names unique.
    """

    report: ProbeReport
    """
    Where every outcome is recorded.
    """

    @property
    def route(self) -> RepositoryRoute:
        """:return: The REST paths of the repository."""
        return RepositoryRoute(self.repository)

    @classmethod
    def describe_environment(cls, runner: CommandRunner) -> dict[str, str]:
        """
        :param runner: Runs the commands that describe the environment.
        :return: What the session runs on, by what was looked at.
        """
        return {
            "python": platform.python_version(),
            "cloud session": str(ClaudeCodeVariable.REMOTE.read()),
            "token variable set": str(
                GitHubCredentialVariable.first_token() is not None
            ),
            "checked-out branch": runner.run("git", "branch", "--show-current").output,
            "git author": runner.run("git", "var", "GIT_AUTHOR_IDENT").output.rsplit(
                " ", 2
            )[0],
            "git": runner.run("git", "--version").first_line,
            "curl": runner.run("curl", "--version").first_line,
            "gh": runner.run("gh", "--version").first_line,
        }

    def record_response(
        self, group: CheckGroup, check: str, response: RestResponse, detail: str = ""
    ) -> bool:
        """
        :param group: What part of the workflow the call answers for.
        :param check: What was tried.
        :param response: What the API answered.
        :param detail: What to record on success instead of the response's summary.
        :return: Whether the call succeeded.
        """
        return self.report.record(
            group,
            check,
            response.succeeded,
            f"{response.status} {detail if response.succeeded and detail else response.summary}".strip(),
            response.seconds,
        )

    # %% the domain model, used live

    def check_library(self, commit: str) -> None:
        """
        :param commit: The commit the check verdict is read on.
        """
        for check in (
            LibraryCheck.AUTHENTICATED_LOGIN,
            LibraryCheck.LABELS,
            LibraryCheck.OPEN_PULL_REQUESTS,
            LibraryCheck.CHECK_STATE,
        ):
            self.check_library_call(check, commit)

    def check_library_call(self, check: LibraryCheck, argument: str) -> None:
        """
        :param check: The call through the library.
        :param argument: What the call needs, if anything.
        """
        result = self.runner.run(
            sys.executable,
            "-m",
            "github_workflow.probe.library_check",
            check,
            self.repository.full_name,
            argument,
        )
        self.report.record(
            CheckGroup.LIBRARY, check, result.succeeded, result.summary, result.seconds
        )

    # %% a notes branch

    def check_notes_branch(self) -> None:
        """
        Push a branch of the workflow's own naming, read it back, and delete it, once
        for each name shape.
        """
        for shape in (BranchName.PLAIN, BranchName.SESSION_STYLE):
            branch = f"{shape}{self.stamp}"
            pushed = self.runner.run(
                "git", "push", "--quiet", "origin", f"HEAD:refs/heads/{branch}"
            )
            if not self.report.record(
                CheckGroup.GIT,
                f"push {branch}",
                pushed.succeeded,
                pushed.summary or "pushed",
                pushed.seconds,
            ):
                continue
            listed = self.runner.run(
                "git", "ls-remote", "origin", f"refs/heads/{branch}"
            )
            self.report.record(
                CheckGroup.GIT,
                f"read {branch} back",
                bool(listed.output),
                listed.summary or "not found",
                listed.seconds,
            )
            deleted = self.runner.run(
                "git", "push", "--quiet", "origin", "--delete", branch
            )
            self.report.record(
                CheckGroup.GIT,
                f"delete {branch}",
                deleted.succeeded,
                deleted.summary or "deleted",
                deleted.seconds,
            )

    # %% the finding boards

    def check_issue_board(self) -> None:
        """
        Take one finding through the board: unreviewed, then rejected with a reason,
        then found again among the rejected.
        """
        repository = self.caller.call(HttpMethod.GET, self.route.root)
        has_issues = repository.succeeded and bool(
            repository.body.get(ProbeJSONKey.HAS_ISSUES)
        )
        self.record_response(
            CheckGroup.ISSUE_BOARD, "issues enabled", repository, str(has_issues)
        )
        if not has_issues:
            return
        label = self.caller.call(
            HttpMethod.POST,
            self.route.labels,
            {
                RestJSONKey.NAME: ProbeText.LABEL,
                ProbeJSONKey.COLOR: ProbeText.LABEL_COLOR,
                RestJSONKey.DESCRIPTION: ProbeText.LABEL_DESCRIPTION,
            },
        )
        self.record_response(
            CheckGroup.ISSUE_BOARD, "create the unreviewed label", label
        )
        issue = self.caller.call(
            HttpMethod.POST,
            self.route.issues(),
            {
                RestJSONKey.TITLE: f"{ProbeText.ISSUE_TITLE} {self.stamp}",
                RestJSONKey.BODY: ProbeText.ISSUE_BODY,
                RestJSONKey.LABELS: [ProbeText.LABEL],
            },
        )
        if self.record_response(
            CheckGroup.ISSUE_BOARD, "file a finding as unreviewed", issue
        ):
            self.walk_finding(issue.body[RestJSONKey.NUMBER])
        deleted = self.caller.call(HttpMethod.DELETE, self.route.label(ProbeText.LABEL))
        self.record_response(CheckGroup.ISSUE_BOARD, "delete the label", deleted)

    def walk_finding(self, number: int) -> None:
        """
        :param number: The finding's issue.
        """
        unreviewed = self.caller.call(
            HttpMethod.GET,
            self.route.issues(labels=ProbeText.LABEL, state=IssueState.OPEN),
        )
        listed = unreviewed.succeeded and any(
            entry[RestJSONKey.NUMBER] == number for entry in unreviewed.body
        )
        self.record_response(
            CheckGroup.ISSUE_BOARD,
            "list the unreviewed board right after filing",
            unreviewed,
            f"finding listed: {listed}",
        )
        comment = self.caller.call(
            HttpMethod.POST,
            self.route.issue_comments(number),
            {RestJSONKey.BODY: ProbeText.REJECTION},
        )
        self.record_response(
            CheckGroup.ISSUE_BOARD, "comment the rejection reason", comment
        )
        closed = self.caller.call(
            HttpMethod.PATCH,
            self.route.issue(number),
            {
                RestJSONKey.STATE: IssueState.CLOSED,
                ProbeJSONKey.STATE_REASON: IssueState.NOT_PLANNED,
            },
        )
        self.record_response(
            CheckGroup.ISSUE_BOARD, "close it as not planned", closed, f"#{number}"
        )
        read = self.caller.call(HttpMethod.GET, self.route.issue(number))
        reason = (
            f"state {read.body.get(RestJSONKey.STATE)}, reason {read.body.get(ProbeJSONKey.STATE_REASON)}"
            if read.succeeded
            else ""
        )
        self.record_response(
            CheckGroup.ISSUE_BOARD, "read it back directly", read, reason
        )
        rejected = self.caller.call(
            HttpMethod.GET,
            self.route.issues(labels=ProbeText.LABEL, state=IssueState.CLOSED),
        )
        reasons = (
            [
                entry.get(ProbeJSONKey.STATE_REASON)
                for entry in rejected.body
                if entry[RestJSONKey.NUMBER] == number
            ]
            if rejected.succeeded
            else []
        )
        self.record_response(
            CheckGroup.ISSUE_BOARD,
            "list the rejected board right after closing",
            rejected,
            f"close reason: {reasons}",
        )

    # %% a draft pull request

    def check_pull_request(self, default_branch: str) -> None:
        """
        Open a draft pull request from a probe branch, read what the signals need from
        it, then close it and delete the branch.

        :param default_branch: The branch the pull request targets.
        """
        base = f"origin/{default_branch}"
        self.runner.run("git", "fetch", "--quiet", "origin", default_branch)
        commit = self.runner.run(
            "git",
            "commit-tree",
            f"{base}^{{tree}}",
            "-p",
            base,
            "-m",
            ProbeText.COMMIT_MESSAGE,
        )
        branch = f"{BranchName.PULL_REQUEST}{self.stamp}"
        pushed = self.runner.run(
            "git", "push", "--quiet", "origin", f"{commit.output}:refs/heads/{branch}"
        )
        if not self.report.record(
            CheckGroup.PULL_REQUEST,
            f"push {branch}",
            pushed.succeeded and commit.succeeded,
            pushed.summary or commit.summary or "pushed",
            pushed.seconds,
        ):
            return
        created = self.caller.call(
            HttpMethod.POST,
            self.route.pull_requests,
            {
                RestJSONKey.TITLE: ProbeText.PULL_REQUEST_TITLE,
                RestJSONKey.BODY: ProbeText.PULL_REQUEST_BODY,
                RestJSONKey.HEAD: branch,
                RestJSONKey.BASE: default_branch,
                RestJSONKey.DRAFT: True,
            },
        )
        if self.record_response(
            CheckGroup.PULL_REQUEST, "open a draft pull request", created
        ):
            self.read_pull_request(
                created.body[RestJSONKey.NUMBER], default_branch, branch, commit.output
            )
        deleted = self.runner.run(
            "git", "push", "--quiet", "origin", "--delete", branch
        )
        self.report.record(
            CheckGroup.PULL_REQUEST,
            f"delete {branch}",
            deleted.succeeded,
            deleted.summary or "deleted",
            deleted.seconds,
        )

    def read_pull_request(self, number: int, base: str, head: str, commit: str) -> None:
        """
        :param number: The draft pull request.
        :param base: The branch it targets.
        :param head: The branch it merges.
        :param commit: The commit at its head.
        """
        pull_request = self.caller.call(HttpMethod.GET, self.route.pull_request(number))
        if pull_request.succeeded:
            body = pull_request.body
            detail = f"draft {body[RestJSONKey.DRAFT]}, mergeable_state {body[RestJSONKey.MERGEABLE_STATE]}, {len(body[ProbeJSONKey.REQUESTED_REVIEWERS])} review requests"
            self.record_response(
                CheckGroup.PULL_REQUEST, "read its state", pull_request, detail
            )
        else:
            self.record_response(
                CheckGroup.PULL_REQUEST, "read its state", pull_request
            )
        threads = self.caller.call(HttpMethod.GET, self.route.review_threads(number))
        self.record_response(
            CheckGroup.PULL_REQUEST, "count its review threads (proxy route)", threads
        )
        comparison = self.caller.call(HttpMethod.GET, self.route.comparison(base, head))
        stale = (
            f"ahead {comparison.body.get(ProbeJSONKey.AHEAD_BY)}, behind {comparison.body.get(ProbeJSONKey.BEHIND_BY)}"
            if comparison.succeeded
            else ""
        )
        self.record_response(
            CheckGroup.PULL_REQUEST, "compare it with its base", comparison, stale
        )
        checks = self.caller.call(HttpMethod.GET, self.route.check_runs(commit))
        runs = (
            f"{checks.body.get(ProbeJSONKey.TOTAL_COUNT)} check runs"
            if checks.succeeded
            else ""
        )
        self.record_response(
            CheckGroup.PULL_REQUEST, "read the checks on its head", checks, runs
        )
        self.check_library_call(LibraryCheck.PULL_REQUEST_REVIEW_STATE, str(number))
        closed = self.caller.call(
            HttpMethod.PATCH,
            self.route.pull_request(number),
            {RestJSONKey.STATE: IssueState.CLOSED},
        )
        self.record_response(CheckGroup.PULL_REQUEST, "close it", closed, f"#{number}")

    # %% signals beside the repository

    def check_signals(self) -> None:
        """
        Read the signals that are not below the repository, which a cloud session's
        proxy may not answer.
        """
        waiting = self.caller.call(HttpMethod.GET, self.route.review_requests())
        count = (
            f"{waiting.body.get(ProbeJSONKey.TOTAL_COUNT)} waiting"
            if waiting.succeeded
            else ""
        )
        self.record_response(
            CheckGroup.SIGNALS,
            "search pull requests waiting on my review",
            waiting,
            count,
        )

    # %% default branch

    def default_branch(self) -> str | None:
        """
        :return: The repository's default branch, ``None`` when the API does not say.
        """
        repository = self.caller.call(HttpMethod.GET, self.route.root)
        if not repository.succeeded:
            return None
        return repository.body[ProbeJSONKey.DEFAULT_BRANCH]
