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
- *rejected*: closed as not planned, with the reason, so later sessions do not raise it
  again

## Notes and progress

- On a notes branch on each repository - the fork, or the repository itself - readable
  from any session on that project.

## Cleaning up

- A branch that is no longer needed - its pull request merged, closed or rejected - is
  listed as ready for deletion in the notes, rather than deleted on the spot: a cloud
  session cannot delete branches.
- A local session deletes every listed branch itself. A GitHub Actions workflow that runs
  when the notes branch is pushed deletes them too, so a cloud session only has to push
  the notes.
- The tool turns on GitHub's own deletion of a merged pull request's branch on every
  repository it works on, so most branches never need listing. Only a local session can:
  a cloud session may read a repository's settings but not change them.
- Issues and pull requests are only ever closed, never deleted.

## Where something is turned off

- Where issues or Actions are turned off, as they are on a new fork, the tool turns them
  on if it can, and otherwise tells me exactly where to do it, with the link.
- A local session can turn them on. A cloud session can see whether issues are on, but
  can neither change it nor see whether Actions are on, so there the tool tells me.

## How the agent reaches git and GitHub

- It reads git directly: status, diffs, history, and fetching.
- Every write - a branch, a commit, a push, a pull request, a stack, the notes - goes
  through the workflow's own commands, which check the rules above before writing. A
  plugin hook denies every direct write, so the rules cannot be skipped by accident.
- Nothing is ever force-pushed. A change low in a stack is an ordinary push; GitHub's
  "Rebase stack" moves the pull requests above it, and I merge stacks on GitHub.

## What the agent may do without asking

- push its own work branch
- save notes and progress
- open draft pull requests

Everything else written to GitHub needs my go-ahead.

## How work is done

- A task such as "do issue 1": small, clear tasks go straight to code, failing test
  first; larger ones get a plan I approve first.
- Pull requests stay small through a standing note, not through a measured limit.
- Dependent pull requests are rare, and use GitHub's native stacks when they happen,
  restacked and merged by GitHub.

## Open questions

- A public repository shows its issues, the unreviewed findings included, publicly.

## Deferred

- Signals about my pull requests on an upstream: a cloud session working in a fork
  cannot reach the upstream's API, so they need another route.
