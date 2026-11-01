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

## What the agent may do without asking

- push its own work branch
- save notes and progress
- open draft pull requests

Everything else written to GitHub needs my go-ahead.

## How work is done

- A task such as "do issue 1": small, clear tasks go straight to code, failing test
  first; larger ones get a plan I approve first.
- Pull requests stay small through a standing note, not through a measured limit.
- Dependent pull requests are rare, and use GitHub's native stacks when they happen.

## Open questions

- Forks start with issues turned off, and a public repository shows its issues publicly.
- A cloud session working in a fork cannot reach the upstream's API, so signals about my
  upstream pull requests need another route.
