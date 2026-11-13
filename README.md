# GitHubWorkflow

A personal GitHub workflow for Claude Code sessions: standing notes and per-branch
progress every session starts with, and every write to git and GitHub made through the
workflow's own commands. It is built on the domain model of git and GitHub in
[`domain_model/`](domain_model), shipped with the plugin as a package of its own.

[TUTORIAL.md](TUTORIAL.md) walks through how the parts work together;
[REQUIREMENTS.md](REQUIREMENTS.md) says what the workflow has to do.

## Architecture

The diagrams in this section are drawn from the source as `[tool.architecture-diagrams]`
in [pyproject.toml](pyproject.toml) declares them: the pre-commit hook draws them anew,
and a test fails when they no longer match the source. Never edit them by hand. The
domain model's own are in its [README](domain_model/README.md#architecture).

### Overview

The parts of the workflow, each a group of its modules, from the entry points down to
the vocabulary every part uses. An arrow from one node to another means the first
imports the second; a node with double side bars stands for a subpackage or a group of
modules.

<!-- diagram: overview -->
```mermaid
flowchart LR
    entry_points[["entry points"]]
    findings[["findings"]]
    guard[["guard"]]
    notes[["notes"]]
    pull_requests[["pull requests"]]
    rules[["rules"]]
    runtime[["runtime"]]
    vocabulary[["vocabulary"]]
    work[["work"]]
    entry_points --> findings
    entry_points --> guard
    entry_points --> notes
    entry_points --> pull_requests
    entry_points --> rules
    entry_points --> runtime
    entry_points --> vocabulary
    entry_points --> work
    findings --> notes
    findings --> vocabulary
    findings --> work
    guard --> vocabulary
    notes --> rules
    notes --> vocabulary
    notes --> work
    pull_requests --> notes
    pull_requests --> rules
    pull_requests --> vocabulary
    pull_requests --> work
    rules --> vocabulary
    runtime --> rules
    runtime --> vocabulary
    work --> notes
    work --> rules
    work --> vocabulary
```
<!-- end of diagram: overview -->

A hollow arrow points from a class to the class it extends, a plain arrow to a class
it holds in the field the arrow is labelled with. Enumerations and errors are left
out.

### Entry points

The commands a session or a hook runs, and what each builds from the session.

<!-- diagram: entry points -->
```mermaid
classDiagram
    direction LR
    class ArchitectureDrawing
    class CommandStep
    class FreshenedCommandStep
    class BranchStartStep
    class BranchSwitchStep
    class BranchDiscardStep
    class CommitStep
    class PushStep
    class DraftStep
    class SyncStep
    class StackOnStep
    class NotesSaveStep
    class DescribeStep
    class LabelStep
    class DetailsStep
    class FindingFileStep
    class FindingPrioritizeStep
    class FindingListStep
    class FindingAcceptStep
    class FindingShelveStep
    class FindingRejectStep
    class FindingCommentStep
    class FindingEditStep
    class FindingProveStep
    class FindingMarkUnprovenStep
    class FindingRecheckStep
    class FindingCloseStep
    class FindingAutomateStep
    class IdeaFileStep
    class CleanupStep
    class CloneStep
    class UpstreamStep
    class ReviewListStep
    class ReviewAddressedStep
    class ReviewReplyStep
    class ReviewResolveStep
    class SectionBuilder
    class SetupBuilder
    class PullRequestsBuilder
    class FindingsBuilder
    class CleanupBuilder
    class FreshnessBuilder
    class UpstreamMergesBuilder
    class RuntimeCheck
    class WorkflowSession
    class SessionStart
    CommandStep <|-- FreshenedCommandStep
    CommandStep <|-- BranchStartStep
    CommandStep <|-- BranchSwitchStep
    CommandStep <|-- BranchDiscardStep
    CommandStep <|-- CommitStep
    FreshenedCommandStep <|-- PushStep
    FreshenedCommandStep <|-- DraftStep
    CommandStep <|-- SyncStep
    CommandStep <|-- StackOnStep
    CommandStep <|-- NotesSaveStep
    FreshenedCommandStep <|-- DescribeStep
    CommandStep <|-- LabelStep
    CommandStep <|-- DetailsStep
    CommandStep <|-- FindingFileStep
    CommandStep <|-- FindingPrioritizeStep
    CommandStep <|-- FindingListStep
    CommandStep <|-- FindingAcceptStep
    CommandStep <|-- FindingShelveStep
    CommandStep <|-- FindingRejectStep
    CommandStep <|-- FindingCommentStep
    CommandStep <|-- FindingEditStep
    CommandStep <|-- FindingProveStep
    CommandStep <|-- FindingMarkUnprovenStep
    CommandStep <|-- FindingRecheckStep
    CommandStep <|-- FindingCloseStep
    CommandStep <|-- FindingAutomateStep
    CommandStep <|-- IdeaFileStep
    CommandStep <|-- CleanupStep
    CommandStep <|-- CloneStep
    CommandStep <|-- UpstreamStep
    CommandStep <|-- ReviewListStep
    CommandStep <|-- ReviewAddressedStep
    CommandStep <|-- ReviewReplyStep
    CommandStep <|-- ReviewResolveStep
    SectionBuilder <|-- SetupBuilder
    SectionBuilder <|-- PullRequestsBuilder
    SectionBuilder <|-- FindingsBuilder
    SectionBuilder <|-- CleanupBuilder
    SectionBuilder <|-- FreshnessBuilder
    SectionBuilder <|-- UpstreamMergesBuilder
    CommandStep --> WorkflowSession : session
    SectionBuilder --> WorkflowSession : session
```
<!-- end of diagram: entry points -->

### Vocabulary

The words every part uses: commands and their arguments, the report's lines, files, environment variables, errors, labels and settings.

<!-- diagram: vocabulary -->
```mermaid
classDiagram
    direction LR
    class ProjectCheckout
    class CommandAuthority
    class SessionRuns
    class SessionRunsOnOwnPullRequest
    class SessionRunsOnPersonsWord
    class PersonRuns
    class ValueCountParsing
    class CommandArgument
    class CommandSpecification
    class RefusalAdvice
    class WorkflowMarker
    class LauncherInstallation
    class FailureReport
    class Emphasis
    class ReportLine
    class SessionStartReport
    class ReportSection
    class ReportGroup
    class WorkflowSettings
    CommandAuthority <|-- SessionRuns
    CommandAuthority <|-- SessionRunsOnOwnPullRequest
    CommandAuthority <|-- SessionRunsOnPersonsWord
    CommandAuthority <|-- PersonRuns
    CommandSpecification --> CommandAuthority : authority
    CommandSpecification --> CommandArgument : arguments
    ReportLine --> Emphasis : emphases
    SessionStartReport --> ReportLine : lines
    ReportGroup --> ReportLine : items
```
<!-- end of diagram: vocabulary -->

### Work

Branches, commits, pushes, drafts, sync and the cleanup of branches.

<!-- diagram: work -->
```mermaid
classDiagram
    direction LR
    class BranchTips
    class DiscardedBranches
    class BranchDiscard
    class KeptBranches
    class CleanupReminder
    class BranchCleanup
    class UnusedCloneRemoval
    class Cleanup
    class WorkflowStep
    class LocalBranchFollowing
    class BranchStart
    class BranchSwitch
    class CommitWork
    class PushWork
    class DescriptionEnding
    class PullRequestRetirement
    class SessionLog
    class Replacement
    class DraftOpening
    class PullRequestOpenedLabelling
    class DescriptionRewrite
    class BranchSync
    class WorkBranchMerge
    class MergeCompletion
    class MergeAbort
    class BaseMerge
    class OpenPullRequestBranch
    class PullRequestMerge
    class StackPlacing
    class NotesSaving
    class RepositoryCloning
    BranchTips <|-- DiscardedBranches
    WorkflowStep <|-- BranchDiscard
    WorkflowStep <|-- BranchCleanup
    WorkflowStep <|-- UnusedCloneRemoval
    WorkflowStep <|-- Cleanup
    WorkflowStep <|-- BranchStart
    WorkflowStep <|-- BranchSwitch
    WorkflowStep <|-- CommitWork
    WorkflowStep <|-- PushWork
    WorkflowStep <|-- DraftOpening
    WorkflowStep <|-- DescriptionRewrite
    WorkflowStep <|-- BranchSync
    WorkflowStep <|-- MergeCompletion
    WorkflowStep <|-- MergeAbort
    WorkflowStep <|-- BaseMerge
    WorkflowStep <|-- PullRequestMerge
    WorkflowStep <|-- StackPlacing
    WorkflowStep <|-- NotesSaving
    WorkflowStep <|-- RepositoryCloning
    BranchDiscard --> PullRequestRetirement : retirement
    KeptBranches --> DiscardedBranches : discarded
    CleanupReminder --> KeptBranches : kept
    BranchCleanup --> KeptBranches : kept
    BranchCleanup --> SessionLog : log
    Cleanup --> BranchCleanup : branches
    Cleanup --> UnusedCloneRemoval : clones
    Replacement --> PullRequestRetirement : retirement
    DraftOpening --> PullRequestOpenedLabelling : issue_labels
    DraftOpening --> DescriptionEnding : ending
    DraftOpening --> Replacement : replacement
    DescriptionRewrite --> DescriptionEnding : ending
```
<!-- end of diagram: work -->

### Rules

The rules every write passes.

<!-- diagram: rules -->
```mermaid
classDiagram
    direction LR
    class WritePolicy
    class PushCheck
    class PushHook
    class OwnedRemote
    class OwnedRemotes
    WritePolicy --> OwnedRemote : remote
    OwnedRemotes --> OwnedRemote : owned
```
<!-- end of diagram: rules -->

### Guard

The guard judging every command a session runs.

<!-- diagram: guard -->
```mermaid
classDiagram
    direction LR
    class SessionCommandApproval
    class CoarseGuard
    class Denial
    class WorkflowAlternative
    class PushAlternative
    class CommitAlternative
    class BranchSwitchAlternative
    class BranchStartAlternative
    class SyncAlternative
    class MergeAlternative
    class CloneAlternative
    class DraftAlternative
    class DescribeAlternative
    class LabelAlternative
    class ReviewReplyAlternative
    class ReviewResolveAlternative
    class ProgramCheck
    class ReadOnlyCheck
    class GitCheck
    class GitHubCliCheck
    class HttpClientCheck
    class CurlCheck
    class WgetCheck
    class WorkflowInvocation
    class CommandGuard
    class ToolGuard
    WorkflowAlternative <|-- PushAlternative
    WorkflowAlternative <|-- CommitAlternative
    WorkflowAlternative <|-- BranchSwitchAlternative
    WorkflowAlternative <|-- BranchStartAlternative
    WorkflowAlternative <|-- SyncAlternative
    WorkflowAlternative <|-- MergeAlternative
    WorkflowAlternative <|-- CloneAlternative
    WorkflowAlternative <|-- DraftAlternative
    WorkflowAlternative <|-- DescribeAlternative
    WorkflowAlternative <|-- LabelAlternative
    WorkflowAlternative <|-- ReviewReplyAlternative
    WorkflowAlternative <|-- ReviewResolveAlternative
    ProgramCheck <|-- ReadOnlyCheck
    ReadOnlyCheck <|-- GitCheck
    ReadOnlyCheck <|-- GitHubCliCheck
    ProgramCheck <|-- HttpClientCheck
    HttpClientCheck <|-- CurlCheck
    HttpClientCheck <|-- WgetCheck
```
<!-- end of diagram: guard -->

### Findings

Findings, their proofs and their labels.

<!-- diagram: findings -->
```mermaid
classDiagram
    direction LR
    class FindingLabelling
    class FindingFiling
    class ProvenFindingFiling
    class OpenFindings
    class FindingListing
    class FindingPrioritization
    class FindingChange
    class FindingAcceptance
    class FindingShelving
    class FindingRejection
    class FindingClosing
    class SessionPullRequestClosing
    class FindingComment
    class FindingEdit
    class FindingProving
    class FindingUnproving
    class FindingRecheck
    class FindingDraftOpening
    class FindingsSummary
    class FindingLabelCompletion
    class PickedLabelCompletion
    class LabelsCompletedStep
    class LabelsCompletedReport
    class FindingAutomation
    class FindingTest
    class ProofAttempt
    class ProofRunner
    class BranchProofRunner
    class Proof
    FindingLabelling <|-- FindingFiling
    FindingFiling <|-- ProvenFindingFiling
    FindingLabelling <|-- FindingPrioritization
    FindingLabelling <|-- FindingChange
    FindingChange <|-- FindingAcceptance
    FindingChange <|-- FindingShelving
    FindingChange <|-- FindingRejection
    FindingChange <|-- FindingClosing
    FindingChange <|-- FindingComment
    FindingChange <|-- FindingEdit
    FindingChange <|-- FindingProving
    FindingChange <|-- FindingUnproving
    FindingLabelling <|-- FindingLabelCompletion
    ProofRunner <|-- BranchProofRunner
    ProvenFindingFiling --> FindingTest : test
    ProvenFindingFiling --> ProofRunner : runner
    FindingClosing --> ProofRunner : runner
    FindingProving --> FindingTest : test
    FindingProving --> ProofRunner : runner
    FindingRecheck --> ProofRunner : runner
    FindingDraftOpening --> FindingRecheck : recheck
    LabelsCompletedStep --> PickedLabelCompletion : completion
    LabelsCompletedReport --> PickedLabelCompletion : completion
    ProofAttempt --> FindingTest : test
    Proof --> FindingTest : test
```
<!-- end of diagram: findings -->

### Pull requests

The own pull request, forks, their upstream and following its reviews.

<!-- diagram: pull requests -->
```mermaid
classDiagram
    direction LR
    class BranchFreshening
    class FreshenedStep
    class FreshnessReport
    class WorkBranchPullRequest
    class PullRequestLabelling
    class ThreadedPullRequest
    class PullRequestThread
    class ReviewThreads
    class ReviewThreadListing
    class ReviewThreadWrite
    class ReviewReply
    class ReviewResolution
    class ReviewAddressing
    class PullRequestSignals
    class PullRequestSignalReader
    class PullRequestOverview
    class PullRequestDetails
    class UpstreamProposal
    class ForkMainSync
    class ForkTips
    class UpstreamSuggestion
    class UpstreamMergeFollowing
    class UpstreamReviewRequest
    class UpstreamReviews
    class DirectUpstreamReviews
    class ForwardedUpstreamReviews
    class UpstreamReviewAnswering
    ReviewThreadWrite <|-- ReviewReply
    ReviewThreadWrite <|-- ReviewResolution
    UpstreamReviews <|-- DirectUpstreamReviews
    UpstreamReviews <|-- ForwardedUpstreamReviews
    FreshenedStep --> BranchFreshening : freshening
    FreshnessReport --> BranchFreshening : freshening
    PullRequestLabelling --> WorkBranchPullRequest : pull_request
    ReviewThreads --> WorkBranchPullRequest : pull_request
    ReviewThreadListing --> WorkBranchPullRequest : pull_request
    ReviewThreadListing --> UpstreamReviews : upstream_reviews
    ReviewThreadWrite --> WorkBranchPullRequest : pull_request
    ReviewAddressing --> WorkBranchPullRequest : pull_request
    PullRequestDetails --> PullRequestSignalReader : reader
```
<!-- end of diagram: pull requests -->

### Notes

The notes branch, the Discussions posted through it, its Actions workflows and the repository's features.

<!-- diagram: notes -->
```mermaid
classDiagram
    direction LR
    class DiscussionPost
    class DiscussionComment
    class DiscussionPosting
    class IdeaFiling
    class DiscussionSessionLog
    class NotesBranch
    class CommandReference
    class CommandLineReference
    class OptionReference
    class ArgumentReference
    class NotesBlock
    class NotesSave
    class UnsavedNotes
    class SwitchedOffFeature
    class RepositorySetup
    class CarriedFile
    DiscussionPost <|-- DiscussionComment
    CommandReference <|-- CommandLineReference
    CommandReference <|-- OptionReference
    CommandReference <|-- ArgumentReference
    DiscussionPosting --> NotesBranch : notes
    IdeaFiling --> DiscussionPosting : posting
    IdeaFiling --> DiscussionPost : post
    DiscussionSessionLog --> DiscussionPosting : posting
    NotesSave --> NotesBranch : notes
```
<!-- end of diagram: notes -->

### Runtime

The runtime the plugin installs, the probe of what a cloud session can reach, and the project's tooling.

<!-- diagram: runtime -->
```mermaid
classDiagram
    direction LR
    class RuntimeSwitch
    class DirectoryLock
    class RuntimeInstallation
    class LibraryCall
    class AuthenticatedLoginCall
    class LabelsCall
    class OpenPullRequestsCall
    class CheckStateCall
    class PullRequestReviewStateCall
    class ResultsPublication
    class ProbeCheckOutcome
    class ProbeReport
    class TimedAnswer
    class Probe
    class ProjectTooling
    LibraryCall <|-- AuthenticatedLoginCall
    LibraryCall <|-- LabelsCall
    LibraryCall <|-- OpenPullRequestsCall
    LibraryCall <|-- CheckStateCall
    LibraryCall <|-- PullRequestReviewStateCall
    ProbeReport --> ProbeCheckOutcome : outcomes
    Probe --> ProbeReport : report
```
<!-- end of diagram: runtime -->

## Licence

This project is licensed under the [Apache License 2.0](LICENSE), except for
`domain_model/src/domain_model/exceptions.py` and
`domain_model/src/domain_model/class_property.py`, which contain code adapted
from [krrood](https://github.com/cram2/krrood) and remain under the GNU Lesser General
Public License, Version 3.

Part of the code and ideas are based on
[basstler](https://github.com/AbdelrhmanBassiouny/basstler) at commit
[`5b6e1b699d8ba69880e5ce15ad0b32c4764b0e60`](https://github.com/AbdelrhmanBassiouny/basstler/tree/5b6e1b699d8ba69880e5ce15ad0b32c4764b0e60),
and changed since. basstler is a personal project by Abdelrhman Bassiouny
(<bido.bassuny@gmail.com>), developed independently of any employer or institution. It is
licensed under the Apache License 2.0 as well; see [NOTICE](NOTICE) for attribution.
