"""
The checks a probe runs, each group answering for one part of the workflow, and each
cleaning up what it created.
"""

from __future__ import annotations

import platform
import sys
import time
from dataclasses import dataclass
from enum import StrEnum
from http import HTTPMethod

from basstler_domain_model.environment import (
    ClaudeCodeVariable,
    GitHubCredentialVariable,
)
from basstler_domain_model.commands import CommandRunner
from basstler_domain_model.git.commands import GitCommandRunner
from basstler_domain_model.github.clients import GitHubApi, RestAnswer
from basstler_domain_model.github.routes import RepositoryRoute
from basstler_domain_model.github.vocabulary import (
    IssueState,
    IssueStateReason,
    RestJSONKey,
    WorkflowRunStatus,
)
from basstler_domain_model.repository import Repository

from github_workflow.locations import ProbeTemplate, RepositoryFile
from github_workflow.probe.library_check import LibraryCheck
from github_workflow.probe.results import CheckGroup, ProbeReport

# %% vocabulary


class WorkflowPlaceholder(StrEnum):
    """
    The names the branch deletion workflow template leaves for the probe to fill in.
    """

    WORKFLOW_BRANCH = "__WORKFLOW_BRANCH__"
    """
    The branch carrying the workflow, which triggers it and is deleted last.
    """

    DELETED_BRANCH = "__DELETED_BRANCH__"
    """
    The other branch the workflow deletes.
    """

    @classmethod
    def filled_workflow(cls, workflow: str, deleted: str) -> str:
        """
        :param workflow: The branch the workflow is pushed on.
        :param deleted: The other branch it deletes.
        :return: The branch deletion workflow, naming both.
        """
        return (
            ProbeTemplate.BRANCH_DELETION_WORKFLOW.read_text()
            .replace(cls.WORKFLOW_BRANCH, workflow)
            .replace(cls.DELETED_BRANCH, deleted)
        )


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
    WORKFLOW_COMMIT_MESSAGE = "Probe workflow deleting the probe's branches"


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

    DELETED_BY_WORKFLOW = "probe/deleted-by-workflow-"
    """
    A branch only a workflow is to delete.
    """

    WORKFLOW = "probe/workflow-"
    """
    The branch carrying the branch deletion workflow.
    """


# %% one timed answer


@dataclass(frozen=True)
class TimedAnswer(RestAnswer):
    """
    What the API answered one call with, and how long it took.
    """

    seconds: float = 0.0
    """
    How long the call took.
    """

    @property
    def summary(self) -> str:
        """:return: The API's own message on a refusal, a count for a list, else the
        start of the text."""
        if not self.text.strip().startswith(("{", "[")):
            return self.text[:200]
        body = self.body
        if isinstance(body, dict) and "message" in body:
            return str(body["message"])
        if isinstance(body, list):
            return f"{len(body)} entries"
        return ""


# %% the probe


@dataclass
class Probe:
    """
    One run of every check against the repository the session works in.
    """

    runner: CommandRunner
    """
    Runs git and the library checks in the checkout.
    """

    github: GitHubApi
    """
    Calls GitHub's API.
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
        self, group: CheckGroup, check: str, response: TimedAnswer, detail: str = ""
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

    def call(
        self, method: HTTPMethod, path: str, payload: dict[str, object] | None = None
    ) -> TimedAnswer:
        """
        :param method: The HTTP method.
        :param path: The path below the API root.
        :param payload: The JSON body, absent for a read.
        :return: What the API answered, and how long it took.
        """
        started = time.monotonic()
        answer = self.github.attempt(method, path, payload)
        return TimedAnswer(
            answer.status,
            answer.text,
            answer.headers,
            round(time.monotonic() - started, 2),
        )

    @staticmethod
    def listed(values: dict[str, object]) -> str:
        """
        :param values: Settings or fields, by name.
        :return: Them as ``name value`` pairs on one line.
        """
        return ", ".join(f"{name} {value}" for name, value in values.items())

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
        repository = self.call(HTTPMethod.GET, self.route.root)
        has_issues = repository.succeeded and bool(
            repository.body.get(RestJSONKey.HAS_ISSUES)
        )
        self.record_response(
            CheckGroup.ISSUE_BOARD, "issues enabled", repository, str(has_issues)
        )
        if not has_issues:
            return
        label = self.call(
            HTTPMethod.POST,
            self.route.labels,
            {
                RestJSONKey.NAME: ProbeText.LABEL,
                RestJSONKey.COLOR: ProbeText.LABEL_COLOR,
                RestJSONKey.DESCRIPTION: ProbeText.LABEL_DESCRIPTION,
            },
        )
        self.record_response(
            CheckGroup.ISSUE_BOARD, "create the unreviewed label", label
        )
        issue = self.call(
            HTTPMethod.POST,
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
        deleted = self.call(HTTPMethod.DELETE, self.route.label(ProbeText.LABEL))
        self.record_response(CheckGroup.ISSUE_BOARD, "delete the label", deleted)

    def walk_finding(self, number: int) -> None:
        """
        :param number: The finding's issue.
        """
        unreviewed = self.call(
            HTTPMethod.GET,
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
        comment = self.call(
            HTTPMethod.POST,
            self.route.issue_comments(number),
            {RestJSONKey.BODY: ProbeText.REJECTION},
        )
        self.record_response(
            CheckGroup.ISSUE_BOARD, "comment the rejection reason", comment
        )
        closed = self.call(
            HTTPMethod.PATCH,
            self.route.issue(number),
            {
                RestJSONKey.STATE: IssueState.CLOSED,
                RestJSONKey.STATE_REASON: IssueStateReason.NOT_PLANNED,
            },
        )
        self.record_response(
            CheckGroup.ISSUE_BOARD, "close it as not planned", closed, f"#{number}"
        )
        read = self.call(HTTPMethod.GET, self.route.issue(number))
        reason = (
            f"state {read.body.get(RestJSONKey.STATE)}, reason {read.body.get(RestJSONKey.STATE_REASON)}"
            if read.succeeded
            else ""
        )
        self.record_response(
            CheckGroup.ISSUE_BOARD, "read it back directly", read, reason
        )
        rejected = self.call(
            HTTPMethod.GET,
            self.route.issues(labels=ProbeText.LABEL, state=IssueState.CLOSED),
        )
        reasons = (
            [
                entry.get(RestJSONKey.STATE_REASON)
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
        created = self.call(
            HTTPMethod.POST,
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
        pull_request = self.call(HTTPMethod.GET, self.route.pull_request(number))
        if pull_request.succeeded:
            body = pull_request.body
            detail = f"draft {body[RestJSONKey.DRAFT]}, mergeable_state {body[RestJSONKey.MERGEABLE_STATE]}, {len(body[RestJSONKey.REQUESTED_REVIEWERS])} review requests"
            self.record_response(
                CheckGroup.PULL_REQUEST, "read its state", pull_request, detail
            )
        else:
            self.record_response(
                CheckGroup.PULL_REQUEST, "read its state", pull_request
            )
        threads = self.call(HTTPMethod.GET, self.route.review_threads(number))
        self.record_response(
            CheckGroup.PULL_REQUEST, "count its review threads (proxy route)", threads
        )
        comparison = self.call(HTTPMethod.GET, self.route.comparison(base, head))
        stale = (
            f"ahead {comparison.body.get(RestJSONKey.AHEAD_BY)}, behind {comparison.body.get(RestJSONKey.BEHIND_BY)}"
            if comparison.succeeded
            else ""
        )
        self.record_response(
            CheckGroup.PULL_REQUEST, "compare it with its base", comparison, stale
        )
        checks = self.call(HTTPMethod.GET, self.route.check_runs(commit))
        runs = (
            f"{checks.body.get(RestJSONKey.TOTAL_COUNT)} check runs"
            if checks.succeeded
            else ""
        )
        self.record_response(
            CheckGroup.PULL_REQUEST, "read the checks on its head", checks, runs
        )
        self.check_library_call(LibraryCheck.PULL_REQUEST_REVIEW_STATE, str(number))
        closed = self.call(
            HTTPMethod.PATCH,
            self.route.pull_request(number),
            {RestJSONKey.STATE: IssueState.CLOSED},
        )
        self.record_response(CheckGroup.PULL_REQUEST, "close it", closed, f"#{number}")

    # %% settings

    def check_repository_settings(self) -> None:
        """
        Read the settings the workflow turns on, and write each back unchanged, to learn
        whether the session may change them.
        """
        repository = self.call(HTTPMethod.GET, self.route.root)
        body = repository.body if repository.succeeded else {}
        settings = {
            key: body[key]
            for key in (RestJSONKey.HAS_ISSUES, RestJSONKey.DELETE_BRANCH_ON_MERGE)
            if body.get(key) is not None
        }
        if not self.record_response(
            CheckGroup.SETTINGS,
            "read the repository settings",
            repository,
            self.listed(settings),
        ):
            return
        written = self.call(HTTPMethod.PATCH, self.route.root, settings)
        self.record_response(CheckGroup.SETTINGS, "write them back unchanged", written)
        permissions = self.call(HTTPMethod.GET, self.route.actions_permissions)
        if not self.record_response(
            CheckGroup.SETTINGS,
            "read the Actions permissions",
            permissions,
            self.listed(permissions.body),
        ):
            return
        unchanged = {
            key: permissions.body[key]
            for key in (RestJSONKey.ENABLED, RestJSONKey.ALLOWED_ACTIONS)
            if key in permissions.body
        }
        written = self.call(HTTPMethod.PUT, self.route.actions_permissions, unchanged)
        self.record_response(CheckGroup.SETTINGS, "write them back unchanged", written)

    # %% deleting branches from a workflow

    def check_workflow_branch_deletion(self) -> None:
        """
        Push a branch for a workflow to delete, then the workflow on a branch of its own,
        wait for its run, and see whether both branches are gone.
        """
        deleted = f"{BranchName.DELETED_BY_WORKFLOW}{self.stamp}"
        workflow = f"{BranchName.WORKFLOW}{self.stamp}"
        pushed = self.runner.run(
            "git", "push", "--quiet", "origin", f"HEAD:refs/heads/{deleted}"
        )
        if not self.report.record(
            CheckGroup.ACTIONS,
            f"push {deleted}",
            pushed.succeeded,
            pushed.summary or "pushed",
            pushed.seconds,
        ):
            return
        commit = self.commit_with_workflow(workflow, deleted)
        pushed = self.runner.run(
            "git", "push", "--quiet", "origin", f"{commit}:refs/heads/{workflow}"
        )
        if self.report.record(
            CheckGroup.ACTIONS,
            f"push the workflow on {workflow}",
            pushed.succeeded,
            pushed.summary or "pushed",
            pushed.seconds,
        ):
            self.wait_for_run(workflow)
        left = [
            branch
            for branch in (deleted, workflow)
            if self.runner.run(
                "git", "ls-remote", "origin", f"refs/heads/{branch}"
            ).output
        ]
        self.report.record(
            CheckGroup.ACTIONS,
            "branches gone afterwards",
            not left,
            f"still there: {', '.join(left)}" if left else "both deleted",
            0.0,
        )

    def commit_with_workflow(self, workflow: str, deleted: str) -> str:
        """
        Build a commit on top of the checked-out one that adds the filled-in workflow,
        leaving the checkout untouched.

        :param workflow: The branch the workflow will be pushed on.
        :param deleted: The other branch it deletes.
        :return: The commit.
        """
        text = WorkflowPlaceholder.filled_workflow(workflow, deleted)
        commit = GitCommandRunner(self.runner.working_directory).commit_files(
            "HEAD",
            {RepositoryFile.BRANCH_DELETION_WORKFLOW: text},
            ProbeText.WORKFLOW_COMMIT_MESSAGE,
        )
        self.report.record(
            CheckGroup.ACTIONS,
            "build a commit carrying the workflow",
            True,
            commit,
            0.0,
        )
        return commit

    def wait_for_run(
        self,
        branch: str,
        timeout_seconds: float = 300.0,
        interval_seconds: float = 10.0,
    ) -> None:
        """
        Wait for the workflow run the push to *branch* started, and record how it ended.

        :param branch: The branch the run was triggered on.
        :param timeout_seconds: How long to wait before giving up.
        :param interval_seconds: How long to wait between looks.
        """
        started = time.monotonic()
        seen = False
        while time.monotonic() - started < timeout_seconds:
            time.sleep(interval_seconds)
            runs = self.call(HTTPMethod.GET, self.route.workflow_runs(branch))
            entries = (
                runs.body.get(RestJSONKey.WORKFLOW_RUNS, []) if runs.succeeded else []
            )
            seen = seen or bool(entries)
            if (
                entries
                and entries[0][RestJSONKey.STATUS] == WorkflowRunStatus.COMPLETED
            ):
                run = entries[0]
                self.report.record(
                    CheckGroup.ACTIONS,
                    "the workflow run",
                    True,
                    f"{run[RestJSONKey.CONCLUSION]} {run[RestJSONKey.HTML_URL]}",
                    round(time.monotonic() - started, 2),
                )
                return
        reason = (
            "a run started but did not finish"
            if seen
            else "no run started: Actions may be off, or the workflow was not accepted"
        )
        self.report.record(
            CheckGroup.ACTIONS,
            "the workflow run",
            False,
            reason,
            round(time.monotonic() - started, 2),
        )

    # %% signals beside the repository

    def check_signals(self) -> None:
        """
        Read the signals that are not below the repository, which a cloud session's
        proxy may not answer.
        """
        waiting = self.call(HTTPMethod.GET, self.route.review_requests())
        count = (
            f"{waiting.body.get(RestJSONKey.TOTAL_COUNT)} waiting"
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
        repository = self.call(HTTPMethod.GET, self.route.root)
        if not repository.succeeded:
            return None
        return repository.body[RestJSONKey.DEFAULT_BRANCH]
