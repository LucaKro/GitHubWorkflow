"""
The checks a probe runs, each group answering for one part of the workflow, and each
cleaning up what it created.
"""

from __future__ import annotations

import platform
import sys
import time
from dataclasses import dataclass
from enum import StrEnum, auto
from http import HTTPMethod

from domain_model.class_property import classproperty
from domain_model.commands import CommandResult, CommandRunner
from domain_model.environment import (
    ClaudeCodeVariable,
    GitHubCredentialVariable,
)
from domain_model.git.commands import GitCommandRunner, GitIdentity
from domain_model.git.remotes import ProposedPush, RemoteBranch
from domain_model.git.revisions import BranchName, Commit, CommitHash, TextFiles
from domain_model.git.working_tree import WorkingTree
from domain_model.github.clients import GitHubApi, RestAnswer
from domain_model.github.rest_models import RestPullRequest
from domain_model.github.routes import RepositoryRoute, StackAction
from domain_model.github.stack_models import Stack
from domain_model.github.vocabulary import (
    IssueState,
    IssueStateReason,
    RestJSONKey,
    WorkflowRunStatus,
)
from domain_model.templates import Placeholder

import github_workflow
from github_workflow.command_line import ArgumentName, RunnableCommand
from github_workflow.locations import ProbeTemplate, RepositoryFile
from github_workflow.probe import library_check
from github_workflow.probe.library_check import LibraryCheck
from github_workflow.probe.results import CheckGroup, EnvironmentFact, ProbeReport
from github_workflow.remotes import OwnedRemote

# %% the template's placeholders


class ProbeWorkflowPlaceholder(Placeholder):
    """
    The names the probe's branch deletion workflow leaves to be filled in.
    """

    WORKFLOW_BRANCH = auto()
    """
    The branch carrying the probe's workflow, which triggers it and is deleted last.
    """

    DELETED_BRANCH = auto()
    """
    The other branch the probe's workflow deletes.
    """


# %% vocabulary


class ProbeText(StrEnum):
    """
    The names and texts the probe creates things with, all marked as the probe's.
    """

    LABEL = "probe-triage"
    """
    The label the probe creates.
    """

    LABEL_COLOR = "ededed"
    """
    Its colour.
    """

    LABEL_DESCRIPTION = "Temporary, created by the cloud probe"
    """
    Its description.
    """

    ISSUE_TITLE = "Probe: finding board lifecycle"
    """
    The title of the issue the probe files.
    """

    ISSUE_BODY = (
        "Created by the cloud probe to test the finding boards; closed by it again."
    )
    """
    Its text.
    """

    REJECTION = "Rejected by the probe: this finding only tests the board."
    """
    The comment the probe rejects its issue with.
    """

    PULL_REQUEST_TITLE = "Probe: draft pull request"
    """
    The title of the draft pull request the probe opens.
    """

    PULL_REQUEST_BODY = "Created by the cloud probe; closed by it again."
    """
    Its description.
    """

    COMMIT_MESSAGE = "Probe commit, never merged"
    """
    The message of the commits the probe pushes.
    """

    WORKFLOW_COMMIT_MESSAGE = "Probe workflow deleting the probe's branches"
    """
    The message of the commit pushing the probe's workflow.
    """

    STACK_LOWER_TITLE = "Probe: lower layer of a stack"
    """
    The title of the lower pull request of the stack the probe builds.
    """

    STACK_UPPER_TITLE = "Probe: upper layer of a stack"
    """
    The title of the upper one.
    """


class ProbeBranchShape(StrEnum):
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

    STACK_LOWER = "probe/stack-lower-"
    """
    The lower pull request of the stack the probe forms.
    """

    STACK_UPPER = "probe/stack-upper-"
    """
    The upper pull request of the stack the probe forms.
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

    @classproperty
    def summary_length(cls) -> int:
        """
        How many characters of a text that is no JSON its summary keeps.
        """
        return 200

    @property
    def summary(self) -> str:
        """:return: The API's own message on a refusal, a count for a list, else the
        start of the text."""
        if not self.text.strip().startswith(("{", "[")):
            return self.text[: self.summary_length]
        body = self.body
        if isinstance(body, dict) and RestJSONKey.MESSAGE in body:
            return str(body[RestJSONKey.MESSAGE])
        if isinstance(body, list):
            return f"{len(body)} entries"
        return ""


# %% the probe


@dataclass
class Probe:
    """
    One run of every check against the repository the session works in.
    """

    git: GitCommandRunner
    """
    Runs git in the checkout.
    """

    github: GitHubApi
    """
    Calls GitHub's API.
    """

    remote: OwnedRemote
    """
    The owner's remote of the repository the session works in, which every write
    goes to.
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
        return RepositoryRoute(self.remote.repository)

    @property
    def tree(self) -> WorkingTree:
        """:return: The working tree of the checkout the probe runs in."""
        return WorkingTree(self.git)

    @property
    def runner(self) -> CommandRunner:
        """:return: Runs the library checks and the stacks command in the checkout."""
        return CommandRunner(self.git.working_directory)

    def branch(self, shape: ProbeBranchShape) -> RemoteBranch:
        """
        :param shape: The name shape.
        :return: This run's branch of that shape, on the repository's remote.
        """
        return self.remote.branch(BranchName(f"{shape}{self.stamp}"))

    @classmethod
    def describe_environment(cls, git: GitCommandRunner) -> dict[str, str]:
        """
        :param git: Runs git in the checkout.
        :return: What the session runs on, by what was looked at.
        """
        branch = WorkingTree(git).checked_out_branch()
        return {
            EnvironmentFact.PYTHON: platform.python_version(),
            EnvironmentFact.CLOUD_SESSION: str(ClaudeCodeVariable.REMOTE.read()),
            EnvironmentFact.TOKEN_VARIABLE_SET: str(
                GitHubCredentialVariable.first_token() is not None
            ),
            EnvironmentFact.CHECKED_OUT_BRANCH: "" if branch is None else branch.name,
            EnvironmentFact.GIT_AUTHOR: git.identity(GitIdentity.AUTHOR).rsplit(" ", 2)[
                0
            ],
            EnvironmentFact.GIT: git.version(),
            EnvironmentFact.GITHUB_CLI: CommandRunner(git.working_directory)
            .run("gh", "--version")
            .first_line,
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

    def record_command(
        self,
        group: CheckGroup,
        check: str,
        result: CommandResult,
        detail: str,
    ) -> bool:
        """
        :param group: What part of the workflow the command answers for.
        :param check: What was tried.
        :param result: The finished command.
        :param detail: What to record on success, when the command printed nothing.
        :return: Whether the command succeeded.
        """
        return self.report.record(
            group, check, result.succeeded, result.summary or detail, result.seconds
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

    def check_library(self, commit: CommitHash) -> None:
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
            library_check.__name__,
            check,
            self.remote.repository.full_name,
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
        for shape in (ProbeBranchShape.PLAIN, ProbeBranchShape.SESSION_STYLE):
            branch = self.branch(shape)
            pushed = ProposedPush(branch, self.tree.head()).publish()
            if not self.record_command(
                CheckGroup.GIT, f"push {branch.name}", pushed, "pushed"
            ):
                continue
            found = branch.exists()
            self.report.record(
                CheckGroup.GIT,
                f"read {branch.name} back",
                found,
                "found" if found else "not found",
                0.0,
            )
            self.delete(CheckGroup.GIT, branch)

    def delete(self, group: CheckGroup, branch: RemoteBranch) -> None:
        """
        :param group: What part of the workflow the branch was pushed for.
        :param branch: The branch to delete from the remote.
        """
        self.record_command(
            group,
            f"delete {branch.name}",
            branch.delete(),
            "deleted",
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

    def check_pull_request(self, default_branch: BranchName) -> None:
        """
        Open a draft pull request from a probe branch, read what the signals need from
        it, then close it and delete the branch.

        :param default_branch: The branch the pull request targets.
        """
        self.remote.fetch(self.remote.branch(default_branch))
        base = self.remote.branch(default_branch).tracking_branch.commit()
        commit = base.write_child(TextFiles({}), ProbeText.COMMIT_MESSAGE)
        branch = self.branch(ProbeBranchShape.PULL_REQUEST)
        pushed = ProposedPush(branch, commit).publish()
        if not self.record_command(
            CheckGroup.PULL_REQUEST, f"push {branch.name}", pushed, "pushed"
        ):
            return
        number = self.open_draft(
            CheckGroup.PULL_REQUEST,
            branch.name,
            default_branch,
            ProbeText.PULL_REQUEST_TITLE,
        )
        if number is not None:
            self.read_pull_request(number, default_branch, branch.name, commit)
            self.close_pull_request(CheckGroup.PULL_REQUEST, number)
        self.delete(CheckGroup.PULL_REQUEST, branch)

    def open_draft(
        self, group: CheckGroup, branch: BranchName, base: BranchName, title: str
    ) -> int | None:
        """
        :param group: What part of the workflow the pull request is opened for.
        :param branch: The branch the pull request merges.
        :param base: The branch it targets.
        :param title: Its title.
        :return: Its number, ``None`` when it could not be opened.
        """
        created = self.call(
            HTTPMethod.POST,
            self.route.pull_requests,
            {
                RestJSONKey.TITLE: title,
                RestJSONKey.BODY: ProbeText.PULL_REQUEST_BODY,
                RestJSONKey.HEAD: branch,
                RestJSONKey.BASE: base,
                RestJSONKey.DRAFT: True,
            },
        )
        if not self.record_response(
            group, f"open a draft pull request for {branch}", created
        ):
            return None
        return created.body[RestJSONKey.NUMBER]

    def close_pull_request(self, group: CheckGroup, number: int) -> None:
        """
        :param group: What part of the workflow the pull request was opened for.
        :param number: The pull request to close.
        """
        closed = self.call(
            HTTPMethod.PATCH,
            self.route.pull_request(number),
            {RestJSONKey.STATE: IssueState.CLOSED},
        )
        self.record_response(group, f"close #{number}", closed)

    def read_pull_request(
        self, number: int, base: BranchName, head: BranchName, commit: CommitHash
    ) -> None:
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

    # %% stacks

    def check_stack(self, default_branch: BranchName) -> None:
        """
        Open two chained draft pull requests, the upper one deliberately targeting the
        default branch, and stack them with the stacks command, which has to retarget
        the upper one first; check both on GitHub, then unstack and close them.

        :param default_branch: The branch the lower pull request targets.
        """
        self.remote.fetch(self.remote.branch(default_branch))
        base = self.remote.branch(default_branch).tracking_branch.commit()
        lower_commit = base.write_child(TextFiles({}), ProbeText.STACK_LOWER_TITLE)
        upper_commit = lower_commit.write_child(
            TextFiles({}), ProbeText.STACK_UPPER_TITLE
        )
        lower = self.branch(ProbeBranchShape.STACK_LOWER)
        upper = self.branch(ProbeBranchShape.STACK_UPPER)
        pushed = [
            ProposedPush(branch, commit).publish()
            for branch, commit in ((lower, lower_commit), (upper, upper_commit))
        ]
        recorded = [
            self.record_command(
                CheckGroup.STACKS, f"push {branch.name}", result, "pushed"
            )
            for branch, result in zip((lower, upper), pushed)
        ]
        if all(recorded):
            self.stack_drafts(lower, upper, default_branch)
        for branch, result in zip((lower, upper), pushed):
            if result.succeeded:
                self.delete(CheckGroup.STACKS, branch)

    def stack_drafts(
        self, lower: RemoteBranch, upper: RemoteBranch, default_branch: BranchName
    ) -> None:
        """
        Open a draft pull request for each branch, both targeting the default branch,
        stack them with the stacks command, and close them again.

        :param lower: The branch of the lower pull request.
        :param upper: The branch of the upper pull request, built on *lower*.
        :param default_branch: The branch both pull requests first target.
        """
        numbers = [
            self.open_draft(CheckGroup.STACKS, branch.name, default_branch, title)
            for branch, title in (
                (lower, ProbeText.STACK_LOWER_TITLE),
                (upper, ProbeText.STACK_UPPER_TITLE),
            )
        ]
        if None not in numbers:
            self.stack_with_command(*numbers, lower.name)
        for number in numbers:
            if number is not None:
                self.close_pull_request(CheckGroup.STACKS, number)

    def stack_with_command(
        self, lower: int, upper: int, lower_branch: BranchName
    ) -> None:
        """
        :param lower: The lower pull request.
        :param upper: The upper pull request, targeting the default branch.
        :param lower_branch: The lower pull request's branch, which the upper one must
            end up targeting.
        """
        command = self.runner.run(
            sys.executable,
            "-m",
            github_workflow.__name__,
            *RunnableCommand.STACK_ON.words_naming(
                ArgumentName.BELOW,
                ArgumentName.ABOVE,
                values={ArgumentName.BELOW: str(lower), ArgumentName.ABOVE: str(upper)},
            ),
        )
        self.record_command(
            CheckGroup.STACKS, f"stacks on {lower} {upper}", command, "stacked"
        )
        upper_read = self.call(HTTPMethod.GET, self.route.pull_request(upper))
        base = (
            RestPullRequest.from_json(upper_read.body).base
            if upper_read.succeeded
            else ""
        )
        self.report.record(
            CheckGroup.STACKS,
            "the upper pull request was retargeted",
            base == lower_branch,
            f"targets {base}",
            upper_read.seconds,
        )
        holding = self.call(HTTPMethod.GET, self.route.stacks_holding(upper))
        stacks = (
            [Stack.from_json(entry) for entry in holding.body]
            if holding.succeeded
            else []
        )
        self.record_response(
            CheckGroup.STACKS,
            "read the stack holding the upper one",
            holding,
            (
                f"stack {stacks[0].number}: {stacks[0].numbers}"
                if stacks
                else "in no stack"
            ),
        )
        if not stacks:
            return
        unstacked = self.call(
            HTTPMethod.POST,
            self.route.stack_action(stacks[0].number, StackAction.UNSTACK),
        )
        self.record_response(CheckGroup.STACKS, "unstack it", unstacked)

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
        deleted = self.branch(ProbeBranchShape.DELETED_BY_WORKFLOW)
        workflow = self.branch(ProbeBranchShape.WORKFLOW)
        pushed = ProposedPush(deleted, self.tree.head()).publish()
        if not self.record_command(
            CheckGroup.ACTIONS, f"push {deleted.name}", pushed, "pushed"
        ):
            return
        commit = self.commit_with_workflow(workflow.name, deleted.name)
        pushed = ProposedPush(workflow, commit).publish()
        if self.record_command(
            CheckGroup.ACTIONS,
            f"push the workflow on {workflow.name}",
            pushed,
            "pushed",
        ):
            self.wait_for_run(workflow.name)
        left = [branch.name for branch in (deleted, workflow) if branch.exists()]
        self.report.record(
            CheckGroup.ACTIONS,
            "branches gone afterwards",
            not left,
            f"still there: {', '.join(left)}" if left else "both deleted",
            0.0,
        )

    def commit_with_workflow(self, workflow: str, deleted: str) -> Commit:
        """
        Build a commit on top of the checked-out one that adds the filled-in workflow,
        leaving the checkout untouched.

        :param workflow: The branch the workflow will be pushed on.
        :param deleted: The other branch it deletes.
        :return: The commit.
        """
        text = Placeholder.fill(
            ProbeTemplate.BRANCH_DELETION_WORKFLOW.read_text(),
            {
                ProbeWorkflowPlaceholder.WORKFLOW_BRANCH: workflow,
                ProbeWorkflowPlaceholder.DELETED_BRANCH: deleted,
            },
        )
        commit = self.tree.head().write_child(
            TextFiles({RepositoryFile.BRANCH_DELETION_WORKFLOW: text}),
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
        branch: BranchName,
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

    def default_branch(self) -> BranchName | None:
        """
        :return: The repository's default branch, ``None`` when the API does not say.
        """
        repository = self.call(HTTPMethod.GET, self.route.root)
        if not repository.succeeded:
            return None
        return BranchName(repository.body[RestJSONKey.DEFAULT_BRANCH])
