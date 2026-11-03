# Requirements

What this workflow has to do, from the interview of 2026-11-01. A design decision that
contradicts one of these changes this file first.

## Where it runs

- Mostly in local sessions, but cloud sessions are a first-class target: the workflow is
  what should make cloud sessions trustworthy enough to use.
- On forks of upstream projects, where pull requests go to an upstream that reviews them,
  and on repositories of my own that have no upstream.
- In both, work reaches the default branch only through branches and pull requests:
  nothing is ever pushed to the default branch directly.
- Only on repositories owned by LucaKro. Every write - a push, a branch, an issue, a
  label, a pull request, a comment - is refused before it is attempted when the
  repository it targets, or the URL of the remote a push goes to, belongs to anyone
  else. Reading other repositories is allowed.

## Cloud sessions

- A cloud session gets the workflow as a plugin enabled on my claude.ai account
  (Customize > Plugins, from the private GitHubWorkflow marketplace): its session start
  installs the runtime from the plugin's own copy, so neither an attached GitHubWorkflow
  nor a setup script is needed, and the repository worked in can be any of mine.
- The cloud environment sets the git identity commits are authored with
  (`GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL`, `GIT_COMMITTER_NAME`, `GIT_COMMITTER_EMAIL`).
- `scripts/cloud-check.sh` checks a cloud session end to end and publishes its report
  to the results branch.

## What a session starts with

Loaded automatically, kept as small as possible and produced by code rather than by the
agent:

- my standing notes
- this branch's progress
- one line per other open pull request on the repository
- warnings about this branch's pull request

## Signals

Code reads them deterministically and reports *that* something is the case, never the
detail; the detail is fetched only when I ask:

- CI failed (which check, and where its log is)
- merge conflict or stale base
- pull requests waiting on me
- unresolved review threads (how many, not what they say)

## Findings outside the current pull request

Recorded as GitHub issues on the repository the session works in - the fork, or the
repository itself when it has no upstream - never acted on in the session that found
them:

- *unreviewed*: an open issue labelled for triage, until I look at it
- *accepted*: an open issue I confirmed; working on it starts with a failing test
- *shelved*: an open issue I set aside for now; it stays on the board, apart from the
  findings waiting on me or on work
- *incorrect*: a finding I rejected, labelled so and closed as not planned, with the
  reason, so later sessions do not raise it again
- Each finding carries a priority the filing session judges: *critical* (breaks the
  default branch, security, or data), *high* (wrong behaviour in normal use), *medium*
  (wrong in edge cases, or a maintainability risk), *low* (cosmetic, or cleanup).
- Only I move a finding out of *unreviewed*; a session accepts, shelves or rejects one
  only when I say so.
- Apart from its stage, a finding may be *proven*: a test fails on the default branch
  as GitHub has it, and is posted on the issue - with the commit it failed on - but
  never committed. A finding stays *unreviewed* when proven; being proven never
  replaces my review.
- The filing session proves a finding when a failing test is easy to write; otherwise
  it files it unproven.
- A test passing on the default branch proves nothing: a bug only on a work branch is
  no finding. Neither does a test that is broken rather than failing - one that cannot
  be collected or set up, or fails on its own import, name or syntax error.
- The code runs the test and decides whether it proves the finding; the agent's word
  is not taken for it. A proof counts only when posted by me or by the account the
  workflow writes as.
- A session works on a finding only when I ask it to, never because it found one easy
  to prove. Working on an *accepted* finding starts with proving it; when no failing
  test can be written, the session marks it *unproven* with the reason, and leaves it
  to me.
- A draft pull request works on a finding only when the finding is *accepted* and
  *proven*, and its test, run again on the default branch, still fails; the draft
  closes the finding when merged. A proof that no longer holds stops the work: the
  session asks me whether the finding is fixed.

## Notes and progress

- On a notes branch on each repository - the fork, or the repository itself - readable
  from any session on that project.

## Cleaning up

- A branch that is no longer needed - its pull request merged, closed or rejected - is
  listed as ready for deletion in the notes, rather than deleted on the spot: a cloud
  session cannot delete branches.
- A throwaway branch - pushed, but no longer needed and never merged - is marked with
  `branch discard`, which lists it on the notes branch with the commit it is at.
- `cleanup` deletes the branches ready for deletion: those whose pull request is closed,
  or that were discarded, and that are still at the commit they were closed or
  discarded at. Where the session may not delete
  branches (a cloud session), it lists them on the notes branch, each with the commit
  it is at, with a GitHub Actions workflow that deletes them when the notes branch is
  pushed - each only while still at that commit - and then empties the list.
- The tool turns on GitHub's own deletion of a merged pull request's branch on every
  repository it works on, so most branches never need listing. Only a local session can:
  a cloud session may read a repository's settings but not change them.
- Issues and pull requests are only ever closed, never deleted.

## Where something is turned off

- Where issues are turned off, as they are on a new fork, the tool turns them on if it
  can, and otherwise tells me exactly where to do it, with the link.
- Where Actions are turned off, the tool never turns them on itself: once on, they run
  every workflow on the repository - on a fork, the upstream's scheduled, release and
  bot workflows too - under my account. It tells me they are off, with the link, and I
  decide.
- A local session can turn issues on. A cloud session can see whether issues are on, but
  can neither change it nor see whether Actions are on, so there the tool tells me.

## How the agent reaches git and GitHub

- It reads git directly: status, diffs, history, and fetching.
- Every write - a branch, a commit, a push, a pull request, a stack, the notes - goes
  through the workflow's own commands, which check the rules above before writing. A
  plugin hook denies every direct write, so the rules cannot be skipped by accident.
- When that hook cannot run - its runtime missing or broken - a coarse stand-in denies
  every call naming git, gh, curl or wget, every GitHub tool and every write to git's
  configuration, and lets everything else run, so a broken runtime stops only what
  could reach git or GitHub. Only when the stand-in cannot run either is every call
  blocked.
- That guard catches accidents, not intent: it reads only the command lines of git, gh,
  curl and wget, through shells and wrappers. A push run any other way - an
  interpreter, a build tool, a script - is caught by a `pre-push` hook the session
  start writes into the checkout, which refuses a push to anyone else's repository or
  to the default branch. It checks only pushes from a Claude Code session (where
  `CLAUDECODE` is set, which the guard refuses to change), so my own pushes from a
  terminal pass unchecked. A checkout with a `pre-push` hook of its own keeps it, and
  the session start says the workflow's is missing.
- Not covered: a write to GitHub's API from an interpreter or a script (including the
  domain model's clients called from a one-off snippet), and a push that skips hooks
  (`--no-verify`) from such a program. Only a token scoped to my repositories (a
  fine-grained token or a GitHub App) stops those, at GitHub.
- Nothing is ever force-pushed. A change low in a stack is an ordinary push; GitHub's
  "Rebase stack" moves the pull requests above it, and I merge stacks on GitHub.

## What the agent may do without asking

- push its own work branch
- save notes and progress
- mark its own throwaway branches as discarded
- open draft pull requests

Everything else written to GitHub needs my go-ahead.

## How work is done

- A task such as "do issue 1": small, clear tasks go straight to code, failing test
  first; larger ones get a plan I approve first. For a finding, that failing test is
  its proof.
- Pull requests stay small through a standing note, not through a measured limit.
- Starting a work branch from the default branch also fast-forwards my local default
  branch to GitHub's, unless it has commits of its own.
- Dependent pull requests are rare, and use GitHub's native stacks when they happen,
  restacked and merged by GitHub.

## Open questions

- A public repository shows its issues, the unreviewed findings included, publicly.

## Deferred

- Signals about my pull requests on an upstream: a cloud session working in a fork
  cannot reach the upstream's API, so they need another route.
- One working copy per local session. Parallel local sessions share a checkout, so one
  session's branch switch moves the branch under every other session - and, where the
  development environment installs the packages from those checkouts, the code they
  run. Each session should work in a git worktree of its own (Claude Code's
  `--worktree`): the workflow tested inside one, and the guard naming that route when it
  blocks `git worktree` or `git clone`.
