"""
Branches kept up to date without anyone asking, at session start and before ``push``,
``draft`` and ``describe``: a fork's default branch with its upstream's, and the
checked-out work branch with the branch its pull request targets; never rebased or
forced.
"""

from __future__ import annotations

from dataclasses import dataclass

from basstler_domain_model.git.commands import RemoteBranch
from basstler_domain_model.github.repository_client import (
    ForkDetails,
    PullRequestsFromForks,
)
from basstler_domain_model.github.vocabulary import PullRequestState

from github_workflow.command_line import CommandOption, RunnableCommand
from github_workflow.counted_noun import CountedNoun
from github_workflow.hooks import ReportLine, Speaker, Tone
from github_workflow.policy import WritePolicy
from github_workflow.report_section import ReportSection
from github_workflow.upstream import ForkMainSync
from github_workflow.work import WorkBranchMerge, WorkflowStep

# %% bringing branches up to date


@dataclass(frozen=True)
class BranchFreshening:
    """
    The fork's default branch fast-forwarded to its upstream's, and the checked-out work
    branch merged with the branch its open pull request targets, or the default branch,
    when that cannot conflict and loses nothing; what cannot be brought up to date this
    way is said instead, for the session to settle with ``sync``.
    """

    policy: WritePolicy
    """
    The checkout, its work branch, the owner's remote and the default branch.
    """

    fork_details: ForkDetails
    """
    Reads which repository the fork was forked from, if any.
    """

    pull_requests: PullRequestsFromForks
    """
    Finds the work branch's pull request.
    """

    def lines(self) -> list[ReportLine]:
        """
        :return: What was brought up to date, and what could not be.
        """
        return [*self.fork_lines(), *self.work_branch_lines()]

    def fork_lines(self) -> list[ReportLine]:
        """
        :return: The fork's default branch fast-forwarded, or why it was not; nothing
            on a repository that is no fork, or a fork up to date.
        """
        upstream = self.fork_details.upstream()
        if upstream is None:
            return []
        sync = ForkMainSync(self.policy, self.fork_details)
        tips = sync.tips(upstream)
        if tips.behind == 0:
            return []
        if tips.ahead:
            return [
                ReportLine(
                    f"{self.policy.default_branch} is "
                    f"{CountedNoun(tips.behind, 'commit', 'commits')} behind "
                    f"{upstream}'s but has {tips.ahead} of its own, so it is not "
                    f"fast-forwarded; ask the person what to do with them",
                    Tone.ACTION,
                )
            ]
        return [ReportLine(f"{sync.fast_forward(upstream, tips)}", Tone.NEWS)]

    def work_branch_lines(self) -> list[ReportLine]:
        """
        :return: The work branch merged with its base, or why it was not; nothing when
            no work branch is checked out, a merge is in progress already, or it is up
            to date.
        """
        git = self.policy.checkout.git
        branch = git.checked_out_branch()
        if branch in {"", self.policy.default_branch} or git.merge_in_progress():
            return []
        base = self.base_branch(branch)
        sync = (
            RunnableCommand.SYNC.usage(CommandOption.BASE)
            if base == self.policy.default_branch
            else RunnableCommand.SYNC.usage(
                CommandOption.ON,
                values={CommandOption.ON: "<the number of the pull request below>"},
            )
        )
        merged = RemoteBranch(self.policy.remote.name, base)
        git.fetch_branch(merged).raise_if_failed()
        if git.contains(merged.tracking_reference, "HEAD"):
            return []
        behind = CountedNoun(
            git.commits_between("HEAD", merged.tracking_reference), "commit", "commits"
        )
        stale = f"{branch} is {behind} behind {base}"
        if git.has_uncommitted_changes():
            return [
                ReportLine(
                    f"{stale}, not merged since the working tree holds "
                    f"changes; commit them, then run `{sync}`",
                    Tone.ACTION,
                )
            ]
        if git.automatic_merge_tree("HEAD", merged.tracking_reference) is None:
            finish = RunnableCommand.SYNC.usage(CommandOption.CONTINUE)
            return [
                ReportLine(
                    f"{stale}, and merging it conflicts; run `{sync}`, "
                    f"resolve the files it names and finish with `{finish}`",
                    Tone.ACTION,
                )
            ]
        done = WorkBranchMerge(self.policy).merge(merged, base)
        return [ReportLine(f"{stale}: {done}", Tone.NEWS)]

    def base_branch(self, branch: str) -> str:
        """
        :param branch: The work branch.
        :return: The branch its open pull request targets, the default branch when it
            has none.
        """
        owner = self.policy.remote.repository.owner
        targets = [
            pull_request.base
            for pull_request in self.pull_requests.pull_requests_from(owner, branch)
            if pull_request.state is PullRequestState.OPEN
        ]
        return targets[0] if targets else self.policy.default_branch


# %% before a command


@dataclass(frozen=True)
class FreshenedStep(WorkflowStep):
    """
    A step run once the branches are brought up to date, saying first what that did.
    """

    freshening: BranchFreshening
    """
    Brings the branches up to date.
    """

    step: WorkflowStep
    """
    The step asked for.
    """

    def run(self) -> str:
        done = [line.text for line in self.freshening.lines()]
        return "; ".join([*done, self.step.run()])


# %% at session start


@dataclass(frozen=True)
class FreshnessReport(ReportSection):
    """
    The branches brought up to date as a session starts, and what could not be.
    """

    freshening: BranchFreshening
    """
    Brings the branches up to date.
    """

    def lines(self) -> list[ReportLine]:
        return [
            ReportLine(Speaker.WORKFLOW.says(line.text), line.tone)
            for line in self.freshening.lines()
        ]
