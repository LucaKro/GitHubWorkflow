# github-workflow-domain-model

A deterministic, Python-native domain model of GitHub pull requests, checks, reviews and
labels, and of the git operations built around them.

## Architecture

The diagrams in this section are drawn from the source as `[tool.architecture-diagrams]`
in [pyproject.toml](pyproject.toml) declares them: the pre-commit hook draws them anew,
and a test fails when they no longer match the source. Never edit them by hand.

An arrow from one node to another means the first imports the second; a node with
double side bars stands for a subpackage or a group of modules.

### Overview

The subpackages and the top-level modules.

<!-- diagram: overview -->
```mermaid
flowchart LR
    architecture[["architecture"]]
    call_effects["call_effects"]
    class_family["class_family"]
    class_property["class_property"]
    claude_code[["claude_code"]]
    code_version["code_version"]
    commands["commands"]
    counted_noun["counted_noun"]
    environment["environment"]
    exceptions["exceptions"]
    git[["git"]]
    github[["github"]]
    locations["locations"]
    markdown["markdown"]
    programs["programs"]
    pytest_run["pytest_run"]
    python_project["python_project"]
    repository["repository"]
    shell["shell"]
    templates["templates"]
    architecture --> class_family
    architecture --> class_property
    architecture --> exceptions
    architecture --> markdown
    architecture --> python_project
    code_version --> class_property
    code_version --> git
    git --> call_effects
    git --> class_family
    git --> class_property
    git --> commands
    git --> environment
    git --> exceptions
    git --> locations
    git --> programs
    git --> repository
    github --> call_effects
    github --> class_property
    github --> code_version
    github --> commands
    github --> environment
    github --> exceptions
    github --> git
    github --> locations
    github --> programs
    github --> repository
    pytest_run --> commands
    pytest_run --> environment
    python_project --> locations
    repository --> class_property
    repository --> exceptions
    repository --> github
    shell --> class_property
```
<!-- end of diagram: overview -->

### Inside `git`

<!-- diagram: git modules -->
```mermaid
flowchart LR
    commands["commands"]
    conflict_markers["conflict_markers"]
    exceptions["exceptions"]
    identity["identity"]
    options["options"]
    reading["reading"]
    references["references"]
    remotes["remotes"]
    revisions["revisions"]
    storage_branch["storage_branch"]
    subcommands["subcommands"]
    working_tree["working_tree"]
    commands --> exceptions
    commands --> options
    commands --> subcommands
    exceptions --> remotes
    exceptions --> revisions
    reading --> options
    reading --> references
    reading --> subcommands
    remotes --> commands
    remotes --> exceptions
    remotes --> options
    remotes --> references
    remotes --> revisions
    remotes --> subcommands
    revisions --> commands
    revisions --> exceptions
    revisions --> options
    revisions --> references
    revisions --> subcommands
    storage_branch --> commands
    storage_branch --> exceptions
    storage_branch --> remotes
    storage_branch --> revisions
    working_tree --> commands
    working_tree --> options
    working_tree --> references
    working_tree --> revisions
    working_tree --> subcommands
```
<!-- end of diagram: git modules -->

### Inside `github`

<!-- diagram: github modules -->
```mermaid
flowchart LR
    answer_recording["answer_recording"]
    clients["clients"]
    closing_lines["closing_lines"]
    commit_checks["commit_checks"]
    credential["credential"]
    discussions["discussions"]
    exceptions["exceptions"]
    issue_events["issue_events"]
    issue_models["issue_models"]
    labels["labels"]
    number_links["number_links"]
    pull_request_models["pull_request_models"]
    readers["readers"]
    reading_calls["reading_calls"]
    replayed_api["replayed_api"]
    repository_client["repository_client"]
    rest_models["rest_models"]
    review_models["review_models"]
    review_writers["review_writers"]
    routes["routes"]
    stack_models["stack_models"]
    stack_placement["stack_placement"]
    vocabulary["vocabulary"]
    answer_recording --> clients
    answer_recording --> exceptions
    answer_recording --> vocabulary
    clients --> credential
    clients --> exceptions
    clients --> pull_request_models
    clients --> vocabulary
    closing_lines --> vocabulary
    commit_checks --> clients
    commit_checks --> pull_request_models
    commit_checks --> rest_models
    commit_checks --> routes
    credential --> exceptions
    issue_events --> vocabulary
    issue_models --> vocabulary
    labels --> exceptions
    pull_request_models --> exceptions
    pull_request_models --> number_links
    pull_request_models --> review_models
    pull_request_models --> vocabulary
    readers --> clients
    readers --> commit_checks
    readers --> exceptions
    readers --> pull_request_models
    readers --> rest_models
    readers --> review_models
    readers --> review_writers
    readers --> routes
    readers --> vocabulary
    reading_calls --> vocabulary
    repository_client --> clients
    repository_client --> commit_checks
    repository_client --> exceptions
    repository_client --> issue_models
    repository_client --> labels
    repository_client --> rest_models
    repository_client --> routes
    repository_client --> stack_models
    repository_client --> vocabulary
    rest_models --> exceptions
    rest_models --> number_links
    rest_models --> pull_request_models
    rest_models --> review_models
    rest_models --> vocabulary
    review_models --> vocabulary
    review_writers --> clients
    review_writers --> review_models
    review_writers --> routes
    review_writers --> vocabulary
    routes --> vocabulary
    stack_models --> vocabulary
    stack_placement --> exceptions
    stack_placement --> repository_client
    stack_placement --> stack_models
    stack_placement --> vocabulary
    vocabulary --> exceptions
```
<!-- end of diagram: github modules -->

A hollow arrow points from a class to the class it extends, a plain arrow to a class
it holds in the field the arrow is labelled with. Enumerations and errors are left
out, and so are JSON models.

### Classes of `git`

<!-- diagram: git classes -->
```mermaid
classDiagram
    direction LR
    class GitCommandResult
    class GitCommandRunner
    class PersonIdentity
    class GitSubcommandArguments
    class ReadingForms
    class AlwaysReadingForms
    class NeverReadingForms
    class PartlyReadingForms
    class ListingReadingForms
    class BranchReadingForms
    class TagReadingForms
    class ConfigReadingForms
    class FirstWordReadingForms
    class RemoteReadingForms
    class StashReadingForms
    class WorktreeReadingForms
    class ReflogReadingForms
    class SubmoduleReadingForms
    class FetchReadingForms
    class ArchiveReadingForms
    class GitCallEffect
    class UnknownGlobalOption
    class ProgramRunningOption
    class WritingSubcommand
    class GitCall
    class Remote
    class UnconfiguredRemote
    class RemoteBranch
    class RemoteTrackingBranch
    class ProposedPush
    class ReferenceUpdate
    class CommitHash
    class BranchName
    class BranchTip
    class Revision
    class TextFiles
    class Commit
    class LocalBranch
    class StorageBranch
    class WorkingTree
    class Merge
    ReadingForms <|-- AlwaysReadingForms
    ReadingForms <|-- NeverReadingForms
    ReadingForms <|-- PartlyReadingForms
    PartlyReadingForms <|-- ListingReadingForms
    ListingReadingForms <|-- BranchReadingForms
    ListingReadingForms <|-- TagReadingForms
    PartlyReadingForms <|-- ConfigReadingForms
    PartlyReadingForms <|-- FirstWordReadingForms
    FirstWordReadingForms <|-- RemoteReadingForms
    FirstWordReadingForms <|-- StashReadingForms
    FirstWordReadingForms <|-- WorktreeReadingForms
    FirstWordReadingForms <|-- ReflogReadingForms
    FirstWordReadingForms <|-- SubmoduleReadingForms
    PartlyReadingForms <|-- FetchReadingForms
    PartlyReadingForms <|-- ArchiveReadingForms
    GitCallEffect <|-- UnknownGlobalOption
    GitCallEffect <|-- ProgramRunningOption
    GitCallEffect <|-- WritingSubcommand
    Remote <|-- UnconfiguredRemote
    Revision <|-- RemoteTrackingBranch
    Revision <|-- Commit
    Revision <|-- LocalBranch
    Remote --> GitCommandRunner : git
    RemoteBranch --> Remote : remote
    RemoteBranch --> BranchName : name
    RemoteTrackingBranch --> RemoteBranch : branch
    ProposedPush --> RemoteBranch : destination
    ProposedPush --> Revision : source
    ReferenceUpdate --> CommitHash : local_commit
    ReferenceUpdate --> CommitHash : remote_commit
    BranchTip --> BranchName : branch
    BranchTip --> CommitHash : commit
    Revision --> GitCommandRunner : git
    Commit --> GitCommandRunner : git
    Commit --> CommitHash : hash
    LocalBranch --> GitCommandRunner : git
    LocalBranch --> BranchName : name
    StorageBranch --> RemoteBranch : branch
    WorkingTree --> GitCommandRunner : git
    Merge --> WorkingTree : tree
```
<!-- end of diagram: git classes -->

### Classes of `github`

The classes calling GitHub's APIs, and recording and replaying their answers:

<!-- diagram: github client classes -->
```mermaid
classDiagram
    direction LR
    class GitHubRead
    class AnsweredRead
    class AnswerRecording
    class RecordingClient
    class ReplayingClient
    class JobLogReader
    class GraphQLClient
    class RestClient
    class GitHubReader
    class RestWriter
    class RestApi
    class RestAnswer
    class NoAutomaticRedirect
    class GitHubApi
    class GitHubToken
    class SendingOptions
    class GraphQLCall
    class GitHubCliEffect
    class GraphQLWrite
    class ApiSending
    class WritingGitHubCliCommand
    class GitHubCliCall
    class WritingGitHubTool
    class RecordedAnswer
    class SentRequest
    class ReplayedApi
    class RepositoryRoute
    GitHubReader <|-- RecordingClient
    GitHubReader <|-- ReplayingClient
    RestClient <|-- GitHubReader
    GraphQLClient <|-- GitHubReader
    RestClient <|-- RestApi
    RestWriter <|-- RestApi
    GitHubReader <|-- GitHubApi
    RestApi <|-- GitHubApi
    JobLogReader <|-- GitHubApi
    GitHubCliEffect <|-- GraphQLWrite
    GitHubCliEffect <|-- ApiSending
    GitHubCliEffect <|-- WritingGitHubCliCommand
    AnsweredRead --> GitHubRead : read
    AnswerRecording --> AnsweredRead : answers
    RecordingClient --> GitHubReader : client
    RecordingClient --> AnswerRecording : recording
    ReplayingClient --> AnswerRecording : recording
    ReplayedApi --> RecordedAnswer : answers
    ReplayedApi --> SentRequest : sent
```
<!-- end of diagram: github client classes -->

The classes reading and writing pull requests, reviews, checks and labels:

<!-- diagram: github reader classes -->
```mermaid
classDiagram
    direction LR
    class ClosingLines
    class CommitCheckReader
    class DiscussionCategory
    class GitHubLabel
    class LabelWrite
    class HasNumberLink
    class CheckResult
    class CheckStatus
    class UpstreamPullRequestSnapshot
    class GraphQLResponse
    class PullRequestSource
    class ReviewThreadSource
    class RestReviewThreadSource
    class GraphQLReviewThreadSource
    class GitHubPullRequestSource
    class ReadSource
    class RestReadSource
    class GraphQLReadSource
    class BranchPullRequest
    class ReviewThreadWriter
    class RestReviewThreadWriter
    class GraphQLReviewThreadWriter
    class StackPlacement
    HasNumberLink <|-- UpstreamPullRequestSnapshot
    ReviewThreadSource <|-- RestReviewThreadSource
    ReviewThreadSource <|-- GraphQLReviewThreadSource
    PullRequestSource <|-- GitHubPullRequestSource
    ReadSource <|-- RestReadSource
    ReadSource <|-- GraphQLReadSource
    ReviewThreadWriter <|-- RestReviewThreadWriter
    ReviewThreadWriter <|-- GraphQLReviewThreadWriter
    CheckStatus --> CheckResult : results
    UpstreamPullRequestSnapshot --> CheckStatus : checks
    GitHubPullRequestSource --> ReviewThreadSource : thread_source
```
<!-- end of diagram: github reader classes -->

The classes of `repository_client`:

<!-- diagram: github repository classes -->
```mermaid
classDiagram
    direction LR
    class PullRequestReader
    class LabelWriter
    class Commenter
    class PullRequestWriter
    class RepositoryLabels
    class PullRequestCloser
    class PullRequestBaseWriter
    class StackReader
    class StackWriter
    class PullRequestOpener
    class ForkDetails
    class PullRequestSearch
    class RepositoryWorkflows
    class ForkSync
    class PullRequestsFromForks
    class RepositoryDetails
    class IssueLabelHistory
    class RepositoryDiscussions
    class RepositorySettings
    class IssueTitleWriter
    class IssueBoard
    class ReviewRequests
    class CommitChecks
    class CredentialHolder
    class PullRequestListingSpecification
    class IssueTracker
    class IssueLabelTracker
    class IssueAndPullRequestTracker
    class ClosablePullRequests
    class RewritablePullRequests
    class PullRequestTracker
    class BranchStacks
    class StackHost
    class RepositoryFeatures
    class FollowedFork
    class ForkedRepository
    class ForkCommenter
    class UpstreamRepository
    class ProposingFork
    class GitHubRepository
    LabelWriter <|-- PullRequestWriter
    Commenter <|-- PullRequestWriter
    LabelWriter <|-- IssueBoard
    Commenter <|-- IssueBoard
    IssueTitleWriter <|-- IssueBoard
    IssueBoard <|-- IssueTracker
    RepositoryLabels <|-- IssueTracker
    IssueTracker <|-- IssueLabelTracker
    IssueLabelHistory <|-- IssueLabelTracker
    PullRequestReader <|-- IssueAndPullRequestTracker
    IssueTracker <|-- IssueAndPullRequestTracker
    IssueAndPullRequestTracker <|-- ClosablePullRequests
    PullRequestCloser <|-- ClosablePullRequests
    PullRequestReader <|-- RewritablePullRequests
    RepositoryDetails <|-- RewritablePullRequests
    PullRequestWriter <|-- RewritablePullRequests
    IssueTitleWriter <|-- RewritablePullRequests
    PullRequestReader <|-- PullRequestTracker
    RepositoryLabels <|-- PullRequestTracker
    ReviewRequests <|-- PullRequestTracker
    PullRequestsFromForks <|-- BranchStacks
    StackReader <|-- BranchStacks
    PullRequestReader <|-- StackHost
    PullRequestBaseWriter <|-- StackHost
    StackReader <|-- StackHost
    StackWriter <|-- StackHost
    RepositorySettings <|-- RepositoryFeatures
    RepositoryDiscussions <|-- RepositoryFeatures
    RepositoryWorkflows <|-- RepositoryFeatures
    PullRequestReader <|-- FollowedFork
    RepositoryDetails <|-- FollowedFork
    ForkDetails <|-- FollowedFork
    StackReader <|-- FollowedFork
    PullRequestsFromForks <|-- ForkedRepository
    ForkDetails <|-- ForkedRepository
    ForkDetails <|-- ForkCommenter
    Commenter <|-- ForkCommenter
    PullRequestsFromForks <|-- UpstreamRepository
    RepositoryDetails <|-- UpstreamRepository
    UpstreamRepository <|-- ProposingFork
    ForkedRepository <|-- ProposingFork
    LabelWriter <|-- ProposingFork
    ForkCommenter <|-- ProposingFork
    RepositoryLabels <|-- ProposingFork
    CredentialHolder <|-- GitHubRepository
    PullRequestSearch <|-- GitHubRepository
    CommitChecks <|-- GitHubRepository
    StackHost <|-- GitHubRepository
    IssueLabelTracker <|-- GitHubRepository
    RepositoryFeatures <|-- GitHubRepository
    PullRequestOpener <|-- GitHubRepository
    ForkSync <|-- GitHubRepository
    BranchStacks <|-- GitHubRepository
    PullRequestTracker <|-- GitHubRepository
    ClosablePullRequests <|-- GitHubRepository
    FollowedFork <|-- GitHubRepository
    ProposingFork <|-- GitHubRepository
    RewritablePullRequests <|-- GitHubRepository
```
<!-- end of diagram: github repository classes -->

## Licence

This project is licensed under the [Apache License 2.0](LICENSE), except for
`src/domain_model/exceptions.py` and
`src/domain_model/class_property.py`, which contain code adapted from
[krrood](https://github.com/cram2/krrood) and remain under the GNU Lesser General
Public License, Version 3.

Part of the code and ideas are based on
[basstler](https://github.com/AbdelrhmanBassiouny/basstler) at commit
[`5b6e1b699d8ba69880e5ce15ad0b32c4764b0e60`](https://github.com/AbdelrhmanBassiouny/basstler/tree/5b6e1b699d8ba69880e5ce15ad0b32c4764b0e60),
and changed since. basstler is a personal project by Abdelrhman Bassiouny
(<bido.bassuny@gmail.com>), developed independently of any employer or institution. It is
licensed under the Apache License 2.0 as well; see [NOTICE](NOTICE) for attribution.
