"""
The repository the owner's fork was forked from: opening a pull request or moving an
issue of the fork there, commands only the person runs, which the description suggests
to them; following the upstream.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Collection
from dataclasses import dataclass, field
from enum import StrEnum

from domain_model.class_property import classproperty
from domain_model.git.remotes import ProposedPush, RemoteBranch
from domain_model.git.revisions import BranchName, BranchTip, Commit
from domain_model.github.labels import LabelWrite
from domain_model.github.closing_lines import ClosingLines
from domain_model.github.issue_models import Issue
from domain_model.github.repository_client import (
    ClosablePullRequests,
    FollowedFork,
    ForkDetails,
    ProposingFork,
    PullRequestSearch,
    UpstreamIssueTracker,
    UpstreamRepository,
)
from domain_model.github.rest_models import RestPullRequest
from domain_model.github.stack_placement import StackPlacement
from domain_model.github.vocabulary import (
    IssueState,
    IssueStateReason,
    PullRequestState,
)
from domain_model.repository import Repository

from github_workflow.command_line import ArgumentName, RunnableCommand
from github_workflow.exceptions import (
    ForeignRepositoryError,
    ForkBranchDivergedError,
    IssueNotMovableError,
    IssueTemplatesRequiredError,
    NotAForkError,
    PersonOnlyCommandError,
    PullRequestNotProposableError,
)
from github_workflow.labels import UpstreamLabel
from github_workflow.plugin import Launcher
from github_workflow.policy import WritePolicy
from github_workflow.proofs import Proof
from github_workflow.remotes import ForkUpstream
from github_workflow.report_lines import CountedThing, ReportLine, Speaker, Tone
from github_workflow.report_section import ReportSection
from github_workflow.settings import WorkflowSettings
from github_workflow.work import (
    DescriptionEnding,
    LocalBranchFollowing,
    PullRequestRetirement,
)
from github_workflow.workflow_step import WorkflowStep

# %% proposing


@dataclass(frozen=True)
class UpstreamProposal(WorkflowStep):
    """
    The open pull request of a branch of the owner's fork opened on the repository the
    fork was forked from, ready for review, with the same title and a description
    linking back to it; the fork's pull request then links to the new one and is
    labelled :attr:`UpstreamLabel.OPENED_UPSTREAM`.

    :raises PersonOnlyCommandError: If a Claude Code session runs it.
    :raises ForeignRepositoryError: If the repository is somebody else's.
    :raises NotAForkError: If the repository was forked from none.
    :raises PullRequestNotProposableError: If the branch has no open pull request onto
        the fork's default branch, or one is open upstream already.
    """

    repository: Repository
    """
    The owner's fork.
    """

    branch: BranchName
    """
    The fork's branch whose pull request is proposed.
    """

    fork: ProposingFork
    """
    The fork: its pull request from the branch, what it was forked from, and the link
    and label put on that pull request.
    """

    upstream_repository: Callable[[Repository], UpstreamRepository]
    """
    Reaches the repository the fork was forked from.
    """

    settings: WorkflowSettings
    """
    Whose forks are proposed from.
    """

    run_by_a_session: bool
    """
    Whether a Claude Code session runs the command.
    """

    def run(self) -> str:
        if self.run_by_a_session:
            raise PersonOnlyCommandError(" ".join(RunnableCommand.UPSTREAM.words))
        if not self.settings.owns(self.repository):
            raise ForeignRepositoryError(self.repository, self.settings.owner)
        upstream = self.fork.upstream()
        if upstream is None:
            raise NotAForkError(self.repository)
        local = self.local_pull_request()
        proposals = self.upstream_repository(upstream)
        already = proposals.open_fork_branch_pull_requests(
            self.repository.owner, self.branch
        )
        if already:
            raise PullRequestNotProposableError(
                self.branch,
                f"its pull request is open on {upstream} already, as "
                f"#{already[0].number}: {already[0].url}",
            )
        opened = proposals.open_fork_pull_request(
            self.repository.owner,
            self.branch,
            proposals.default_branch(),
            local.title,
            self.body_linking(local.url),
        )
        self.fork.add_comment(local.number, self.comment_linking(opened.url))
        self.fork.create_missing_labels([UpstreamLabel.OPENED_UPSTREAM])
        self.fork.replace_labels(
            local.number,
            LabelWrite.from_changes(
                local.labels, [UpstreamLabel.OPENED_UPSTREAM]
            ).labels,
        )
        return f"opened {upstream}#{opened.number}: {opened.url}"

    def local_pull_request(self) -> RestPullRequest:
        """
        :return: The fork's open pull request from the branch, onto its default branch.
        :raises PullRequestNotProposableError: If there is none.
        """
        every = self.fork.fork_branch_pull_requests(self.repository.owner, self.branch)
        if not every:
            raise PullRequestNotProposableError(
                self.branch, f"{self.repository} has no pull request from it"
            )
        open_ones = [
            pull_request
            for pull_request in every
            if pull_request.state is PullRequestState.OPEN
        ]
        if not open_ones:
            latest = max(every, key=lambda pull_request: pull_request.number)
            raise PullRequestNotProposableError(
                self.branch,
                f"its pull request #{latest.number} is {latest.state}, not open",
            )
        default_branch = self.fork.default_branch()
        onto_default = [
            pull_request
            for pull_request in open_ones
            if pull_request.base == default_branch
        ]
        if not onto_default:
            stacked = open_ones[0]
            raise PullRequestNotProposableError(
                self.branch,
                f"its pull request #{stacked.number} is stacked on {stacked.base}, not "
                f"onto {default_branch}: open the one below upstream first",
            )
        return onto_default[0]

    @staticmethod
    def body_linking(url: str) -> str:
        """
        :param url: The fork's pull request.
        :return: The new pull request's description.
        """
        return f"Proposed from {url}"

    @classproperty
    def link_prefix(cls) -> str:
        """
        How the comment on the fork's pull request linking the one upstream starts.
        """
        return "Opened upstream: "

    @classmethod
    def comment_linking(cls, url: str) -> str:
        """
        :param url: The new pull request upstream.
        :return: The comment on the fork's pull request.
        """
        return f"{cls.link_prefix}{url}"

    @classmethod
    def read_linked_url(cls, comment: str) -> str | None:
        """
        :param comment: A comment on the fork's pull request.
        :return: The pull request upstream it links, ``None`` when it links none.
        """
        if not comment.startswith(cls.link_prefix):
            return None
        return comment.removeprefix(cls.link_prefix).split()[0]


# %% following the upstream


@dataclass(frozen=True)
class ForkMainSync(WorkflowStep):
    """
    The fork's default branch fast-forwarded to the same branch of the repository it was
    forked from, as GitHub's *Sync fork* does, and the local copy after it, through git
    alone: the upstream's branch fetched and pushed to the fork, never merged or
    forced.

    .. note:: The push skips the checkout's ``pre-push`` hook, which refuses every
       change to the default branch: this fast-forward to the upstream's commit is the
       one the workflow makes itself.

    :raises NotAForkError: If the repository was forked from none.
    :raises ForkBranchDivergedError: If the fork's branch has commits of its own.
    """

    policy: WritePolicy
    """
    The checkout of the owner's fork, and its default branch.
    """

    fork_details: ForkDetails
    """
    Reads which repository the fork was forked from.
    """

    def run(self) -> str:
        repository = self.policy.remote.repository
        upstream = self.fork_details.upstream()
        if upstream is None:
            raise NotAForkError(repository)
        tips = self.tips(upstream)
        branch = self.policy.default_branch
        if tips.ahead == tips.behind == 0:
            return f"{branch} is up to date with {upstream}'s"
        if tips.ahead:
            raise ForkBranchDivergedError(branch, upstream, tips.ahead)
        return self.fast_forward(upstream, tips)

    @property
    def fork_branch(self) -> RemoteBranch:
        """:return: The fork's default branch, on the owner's remote."""
        return self.policy.remote.branch(self.policy.default_branch)

    def tips(self, upstream: Repository) -> ForkTips:
        """
        :param upstream: The repository the fork was forked from.
        :return: The fork's default branch and the upstream's, as fetched now.
        :raises UpstreamRemoteNameTakenError: If the upstream cannot be fetched under
            its remote's name.
        """
        remote = ForkUpstream(self.policy.checkout.git, upstream).remote()
        fork = self.fork_branch
        theirs = remote.branch(self.policy.default_branch)
        fork.fetch().raise_if_failed()
        theirs.fetch().raise_if_failed()
        fork_commit = fork.tracking_branch.commit()
        upstream_commit = theirs.tracking_branch.commit()
        return ForkTips(
            BranchTip(fork.name, fork_commit.hash),
            BranchTip(theirs.name, upstream_commit.hash),
            fork_commit.commits_ahead(upstream_commit),
            upstream_commit.commits_ahead(fork_commit),
        )

    def fast_forward(self, upstream: Repository, tips: ForkTips) -> str:
        """
        :param upstream: The repository the fork was forked from.
        :param tips: The two branches' tips, the fork's behind and with no commits of
            its own.
        :return: What was fast-forwarded, the local copy included.
        """
        checkout = self.policy.checkout
        fork = self.fork_branch
        upstream_commit = Commit(checkout.git, tips.upstream.commit)
        ProposedPush(
            fork, upstream_commit, runs_push_hook=False
        ).publish().raise_if_failed()
        fork.fetch().raise_if_failed()
        local = LocalBranchFollowing(checkout.working_tree).follow(fork)
        behind = CountedThing.COMMIT.quantify(tips.behind)
        return f"{fork.name} fast-forwarded by {behind} to {upstream}'s{local}"


@dataclass(frozen=True)
class ForkTips:
    """
    A fork's default branch and the same branch of the repository it was forked from.
    """

    fork: BranchTip
    """
    The fork's tip.
    """

    upstream: BranchTip
    """
    The upstream's tip.
    """

    ahead: int
    """
    How many commits the fork has that the upstream lacks.
    """

    behind: int
    """
    How many commits the upstream has that the fork lacks.
    """


# %% the suggestion


@dataclass(frozen=True)
class PersonCommandEnding:
    """
    The end of a pull request's or issue's description giving the person a command line
    only they may run, for them to copy.
    """

    purpose: str
    """
    What the command does, as the sentence introducing it finishes ``To ...``.
    """

    command: str
    """
    The command line.
    """

    @property
    def text(self) -> str:
        """
        The ending itself.
        """
        return (
            f"---\n\n"
            f"To {self.purpose}, run this yourself (a Claude Code session may not):\n\n"
            f"```bash\n{self.command}\n```"
        )

    def remove(self, body: str) -> str:
        """
        :param body: A description, which may hold the ending.
        :return: The description without it.
        """
        return body.replace(self.text, "").rstrip()

    def append_once(self, body: str) -> str:
        """
        :param body: A description, which may hold the ending already.
        :return: The description, ending with it once.
        """
        return f"{self.remove(body)}\n\n{self.text}\n"


@dataclass(frozen=True)
class UpstreamSuggestion(DescriptionEnding):
    """
    The command line opening a fork's pull request upstream, ending its description for
    the person to copy; nothing on a repository that is no fork.
    """

    fork_details: ForkDetails
    """
    Reads whether the repository is a fork.
    """

    repository: Repository
    """
    The repository the pull request is opened on.
    """

    def append_once(self, body: str, branch: BranchName) -> str:
        upstream = self.fork_details.upstream()
        if upstream is None:
            return body
        return PersonCommandEnding(
            f"open this pull request on {upstream}",
            self.opening_command(self.repository, branch),
        ).append_once(body)

    @staticmethod
    def opening_command(repository: Repository, branch: BranchName) -> str:
        """
        :param repository: The owner's fork.
        :param branch: Its branch.
        :return: The command line opening the branch's pull request upstream, as the
            person runs it on their own machine.
        """
        words = RunnableCommand.UPSTREAM.words_naming(
            ArgumentName.REPOSITORY,
            ArgumentName.BRANCH,
            values={
                ArgumentName.REPOSITORY: repository.full_name,
                ArgumentName.BRANCH: branch,
            },
        )
        return " ".join([Launcher.COMMAND, *words])


# %% findings filed on a fork


@dataclass(frozen=True)
class IssueMoveSuggestion:
    """
    The command line moving an issue of the owner's fork upstream, ending the issue's
    text for the person to copy; nothing on a repository that is no fork.
    """

    repository: Repository
    """
    The repository the issue is on.
    """

    fork_details: ForkDetails
    """
    Reads which repository it was forked from.
    """

    def append_once(self, body: str, number: int) -> str:
        """
        :param body: The issue's text, which may end with the command line already.
        :param number: The issue.
        :return: The text, ending with the command line once.
        """
        upstream = self.fork_details.upstream()
        if upstream is None:
            return body
        ending = IssueUpstreamMove.ending(self.repository, number, upstream)
        return ending.append_once(body)


# %% moving an issue


class Confirmation(ABC):
    """
    Asks the person running a command a question they answer yes or no.
    """

    @abstractmethod
    def confirm(self, question: str) -> bool:
        """
        :param question: The question.
        :return: Whether the person answered yes.
        """


class AffirmativeAnswer(StrEnum):
    """
    The answers on a terminal that mean yes, in any case.
    """

    YES = "yes"
    """
    The word.
    """

    LETTER = "y"
    """
    Its first letter.
    """


@dataclass(frozen=True)
class TerminalConfirmation(Confirmation):
    """
    Asks on the terminal the command runs in; anything but a yes is a no.
    """

    def confirm(self, question: str) -> bool:
        answer = input(f"{question} [{AffirmativeAnswer.LETTER}/N] ")
        return answer.strip().casefold() in set(AffirmativeAnswer)


@dataclass(frozen=True)
class IssueUpstreamMove(WorkflowStep):
    """
    An open issue of the owner's fork opened on the repository it was forked from, as
    the person, with its title and text but none of its labels or the command moving
    it, and its latest proof; then closed on the fork, linking the new one, with the
    fork's open pull requests closing it, once the person agrees.

    :raises PersonOnlyCommandError: If a Claude Code session runs it.
    :raises ForeignRepositoryError: If the repository is somebody else's.
    :raises NotAForkError: If the repository was forked from none.
    :raises IssueNotMovableError: If the issue is closed, or the person keeps the pull
        requests closing it.
    :raises IssueTemplatesRequiredError: If the upstream files issues through templates
        and the issue was not rewritten to follow them; it is labelled
        :attr:`UpstreamLabel.TEMPLATE_REQUIRED` and given a comment linking them.
    """

    repository: Repository
    """
    The owner's fork.
    """

    number: int
    """
    The fork's issue.
    """

    fork: ClosablePullRequests
    """
    The fork's issues and pull requests.
    """

    fork_details: ForkDetails
    """
    Reads which repository the fork was forked from.
    """

    upstream_repository: Callable[[Repository], UpstreamIssueTracker]
    """
    Reaches the repository the fork was forked from.
    """

    settings: WorkflowSettings
    """
    Whose forks issues are moved from.
    """

    confirmation: Confirmation
    """
    Asks the person whether to close the pull requests closing the issue.
    """

    run_by_a_session: bool = field(kw_only=True)
    """
    Whether a Claude Code session runs the command.
    """

    follows_template: bool = field(kw_only=True)
    """
    Whether the issue was rewritten to follow the upstream's issue templates.
    """

    proof_authors: Collection[str] = field(kw_only=True)
    """
    The logins whose proofs on the issue count.
    """

    def run(self) -> str:
        if self.run_by_a_session:
            words = RunnableCommand.ISSUE_UPSTREAM.words
            raise PersonOnlyCommandError(" ".join(words))
        if not self.settings.owns(self.repository):
            raise ForeignRepositoryError(self.repository, self.settings.owner)
        upstream = self.fork_details.upstream()
        if upstream is None:
            raise NotAForkError(self.repository)
        issue = self.fork.issue(self.number)
        if issue.state is not IssueState.OPEN:
            raise IssueNotMovableError(self.number, "it is closed")
        target = self.upstream_repository(upstream)
        if not self.follows_template:
            self.check_templates(issue, upstream, target.issue_templates())
        closing = self.agreed_closing_pull_requests()
        body = self.ending(self.repository, self.number, upstream).remove(issue.body)
        opened = target.open_issue(issue.title, body, [])
        url = upstream.issue_url(opened)
        comments = self.fork.comments(self.number)
        proof = Proof.latest_posted_comment(comments, self.proof_authors)
        if proof is not None:
            origin = self.repository.issue_url(self.number)
            target.add_comment(opened, f"Proven on {origin}:\n\n{proof.body}")
        for pull_request in closing:
            self.fork.add_comment(pull_request.number, f"Its issue moved to {url}.")
            self.fork.close_pull_request(pull_request.number)
        self.fork.add_comment(self.number, f"Moved upstream: {url}")
        self.fork.close_issue(self.number, IssueStateReason.NOT_PLANNED)
        closed = [f"#{self.number}", *(each.markdown_link for each in closing)]
        return f"opened [{upstream}#{opened}]({url}); closed {', '.join(closed)}"

    def check_templates(
        self, issue: Issue, upstream: Repository, templates: list[str]
    ) -> None:
        """
        Label the issue and link the templates on it, once, when there are any.

        :param issue: The fork's issue.
        :param upstream: The repository it is moved to.
        :param templates: The pages of the upstream's issue templates.
        :raises IssueTemplatesRequiredError: If there are any.
        """
        if not templates:
            return
        if UpstreamLabel.TEMPLATE_REQUIRED not in issue.labels:
            listed = "\n".join(f"- {template}" for template in templates)
            self.fork.create_missing_labels([UpstreamLabel.TEMPLATE_REQUIRED])
            self.fork.add_labels(self.number, [UpstreamLabel.TEMPLATE_REQUIRED])
            self.fork.add_comment(
                self.number,
                f"{upstream} files issues through these templates; rewrite this issue "
                f"to follow them before moving it there:\n\n{listed}",
            )
        raise IssueTemplatesRequiredError(self.number, upstream, tuple(templates))

    def agreed_closing_pull_requests(self) -> list[RestPullRequest]:
        """
        :return: The fork's open pull requests whose description closes the issue,
            which the person agreed to close.
        :raises IssueNotMovableError: If the person did not agree.
        """
        closing = [
            pull_request
            for pull_request in self.fork.open_pull_requests()
            if self.number in ClosingLines(pull_request.body or "").issues()
        ]
        if not closing:
            return []
        links = ", ".join(pull_request.url for pull_request in closing)
        question = (
            f"#{self.number} is closed by the open pull requests {links}; close them "
            f"and move it?"
        )
        if not self.confirmation.confirm(question):
            raise IssueNotMovableError(
                self.number, "the pull requests closing it stay open"
            )
        return closing

    @staticmethod
    def ending(
        repository: Repository, number: int, upstream: Repository
    ) -> PersonCommandEnding:
        """
        :param repository: The owner's fork.
        :param number: Its issue.
        :param upstream: The repository the fork was forked from.
        :return: The end of the issue's text giving the person the command line moving
            it there.
        """
        words = RunnableCommand.ISSUE_UPSTREAM.words_naming(
            ArgumentName.REPOSITORY,
            ArgumentName.NUMBER,
            values={
                ArgumentName.REPOSITORY: repository.full_name,
                ArgumentName.NUMBER: str(number),
            },
        )
        command = " ".join([Launcher.COMMAND, *words])
        return PersonCommandEnding(f"move this issue to {upstream}", command)


# %% following merges upstream


@dataclass(frozen=True)
class UpstreamMergeFollowing(ReportSection):
    """
    The fork's pull requests opened upstream whose pull request there was merged: each
    one still open closed on the fork as merged upstream, and what is stacked on it,
    also on one the fork has merged already, moved onto the default branch.
    """

    owner: str
    """
    The fork's owner, whose branches the upstream's pull requests are opened from.
    """

    fork: FollowedFork
    """
    The owner's fork on GitHub.
    """

    upstream_search: Callable[[Repository], PullRequestSearch]
    """
    Searches a repository's pull requests: the upstream's.
    """

    closing: PullRequestRetirement
    """
    Closes a fork's pull request as a session's.
    """

    placement: StackPlacement
    """
    Moves a stack off the pull request merged.
    """

    def lines(self) -> list[ReportLine]:
        default_branch = self.fork.default_branch()
        opened = [
            pull_request
            for pull_request in self.pull_requests_to_follow(default_branch)
            if UpstreamLabel.OPENED_UPSTREAM in pull_request.labels
        ]
        if not opened:
            return []
        upstream = self.fork.upstream()
        if upstream is None:
            return []
        search = self.upstream_search(upstream)
        lines = []
        for pull_request in opened:
            linked = self.linked_upstream(pull_request.number)
            merged = [
                found
                for found in search.search_branch_pull_requests(
                    self.owner, pull_request.head.branch
                )
                if found.merged_at is not None and found.url == linked
            ]
            if not merged:
                continue
            done = self.follow_merge(pull_request, merged[0].url, default_branch)
            link = pull_request.markdown_link
            lines.append(
                ReportLine(
                    Speaker.WORKFLOW.says(
                        f"{link} was merged upstream as {merged[0].url}: "
                        f"{', and '.join(done)}; tell the person"
                    ),
                    Tone.ACTION,
                )
            )
        return lines

    def linked_upstream(self, number: int) -> str | None:
        """
        :param number: A fork's pull request opened upstream.
        :return: The pull request upstream the owner's latest comment on it links,
            ``None`` when none does.
        """
        links = [
            UpstreamProposal.read_linked_url(comment.body)
            for comment in self.fork.comments(number)
            if comment.author == self.owner
        ]
        return next((link for link in reversed(links) if link is not None), None)

    def pull_requests_to_follow(
        self, default_branch: BranchName
    ) -> list[RestPullRequest]:
        """
        :param default_branch: The fork's default branch.
        :return: The fork's open pull requests, and each merged one an open pull
            request is still stacked on.
        """
        open_ones = self.fork.open_pull_requests()
        merged_below = []
        for pull_request in open_ones:
            if pull_request.base == default_branch:
                continue
            stack = self.fork.containing_stack(pull_request.number)
            if stack is None:
                continue
            position = stack.numbers.index(pull_request.number)
            if position == 0:
                continue
            below = self.fork.pull_request(stack.numbers[position - 1])
            if below.merged:
                merged_below.append(below)
        return open_ones + merged_below

    def follow_merge(
        self,
        pull_request: RestPullRequest,
        upstream_url: str,
        default_branch: BranchName,
    ) -> list[str]:
        """
        :param pull_request: The fork's pull request merged upstream.
        :param upstream_url: The upstream pull request it was merged as.
        :param default_branch: The fork's default branch.
        :return: What was done on the fork, each in a few words.
        """
        done = []
        if pull_request.state is PullRequestState.OPEN:
            self.closing.retire(
                pull_request.number, f"Merged upstream as {upstream_url}."
            )
            done.append("closed it")
        moved = self.placement.move_off(pull_request.number, default_branch)
        if moved is not None:
            done.append(f"moved #{moved} onto {default_branch}")
        return done
