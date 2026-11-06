# Requirements

What this workflow has to do, from the interview of 2026-11-01. A design decision that
contradicts one of these changes this file first.

## Where it runs

- Mostly in local sessions, but cloud sessions are a first-class target: the workflow is
  what should make cloud sessions trustworthy enough to use.
- On forks of upstream projects, where pull requests go to an upstream that reviews them,
  and on repositories of my own that have no upstream.
- In both, work reaches the default branch only through branches and pull requests:
  nothing is ever pushed to the default branch directly. The one exception is a fork's
  default branch following its upstream's: `sync --upstream` fast-forwards it to the
  upstream's branch of the same name, as GitHub's *Sync fork* does, then the local copy,
  comparing the two with git (a cloud session's proxy refuses GitHub's cross-fork
  compares);
  it refuses when the fork's branch has commits of its own, and never merges or forces.
- Only on repositories owned by LucaKro. Every write - a push, a branch, an issue, a
  label, a pull request, a comment - is refused before it is attempted when the
  repository it targets, or the URL of the remote a push goes to, belongs to anyone
  else. Reading other repositories is allowed. The one write to somebody else's
  repository is `upstream`, which only I run (see below).
- Reading includes cloning: `clone` clones anyone's repository, so a session can read an
  upstream's pull request. Every clone it makes carries the workflow's `pre-push` hook,
  so nothing is pushed from a clone of somebody else's repository, however the push is
  started. The session does not choose where a clone goes: one of my repositories goes
  next to the checkout, somebody else's into the plugin's own data directory, which
  Claude Code gives the plugin's hooks and the session start passes on, as
  `clones/<owner>/<name>`. So it stays out of my directories and never collides with
  the fork's checkout of the same name. Without that directory, somebody else's
  repository is not cloned. A repository cloned before is reused. A pull request's head
  is then fetched into a remote-tracking reference, which only reads. `cleanup` removes
  the clones no session has made or fetched into for a week.

## Cloud sessions

- A cloud session gets the workflow as a plugin enabled on my claude.ai account
  (Customize > Plugins, from the private GitHubWorkflow marketplace): its session start
  installs the runtime from the plugin's own copy, so neither an attached GitHubWorkflow
  nor a setup script is needed, and the repository worked in can be any of mine.
- The runtime reaches no package index: both packages are pure Python without
  dependencies, so it runs their source, the plugin's own copy and the domain model's
  at its pinned commit, fetched from GitHub. A session whose network allows GitHub but
  not PyPI still gets the guard.
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
- What the workflow itself refused unnecessarily, or lacks, is a finding on GitHubWorkflow
  (or on the domain model, for git and GitHub themselves), filed from any session with
  `--repository`, no checkout needed: unproven, with what was run, what happened and
  what should have. Every refusal, the guard's and the commands', and the notes header
  end with how; `finding list --repository` shows first whether it is filed already.
- A session files a finding on its own, never asking me whether to; I review them on
  GitHub.
- Only I move a finding out of *unreviewed*; a session accepts, shelves or rejects one
  only when I say so.
- A session closes a finding on its own only as fixed: an *accepted*, proven finding
  on my repository, once the pull request fixing it is merged into the default branch
  and its proof test passes there (`finding close <number> --fixed-by <pull request>`).
  It closes it as completed, with a comment naming the pull request and the label
  `closed by session`, and tells me in chat. Closing as not planned or as a duplicate,
  an unproven finding, or an issue that is no finding stays mine.
- A stage I pick on GitHub counts at once, even while the label it replaces is still on
  (a repository without the label workflow keeps it): my pick outranks *unreviewed*, and
  of several I picked, the most cautious counts - *incorrect*, then *shelved*, then
  *accepted*. Each finding is listed and counted once, under that stage. The label
  workflow, where a repository has it, only tidies the labels; no fork needs it on its
  default branch.
- Apart from its stage, a finding may be *proven*: a test fails on the default branch
  as GitHub has it, and is posted on the issue - with the commit it failed on - but
  never committed. A finding stays *unreviewed* when proven; being proven never
  replaces my review.
- The filing session proves a finding when a failing test is easy to write; otherwise
  it files it unproven.
- A test passing on the default branch proves nothing: a bug only on a work branch is
  no finding. Neither does a test that is broken rather than failing - one that cannot
  be collected or set up, or fails on its own import, name or syntax error.
- The test imports the default branch's packages, a uv workspace's members' included,
  ahead of any the interpreter has installed from the working checkout.
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
  session asks me whether the finding is fixed. A test that did not run, run again, is
  broken, never "no longer fails", and says what pytest reported.

## Ideas

- An idea is not a finding: `idea file` posts it to the repository's Discussions, in
  the Ideas category unless another is named, with no finding status and no priority.
  A session posts one only when I ask for it.
- A cloud session cannot write Discussions itself (GitHub's only API for writing them
  is GraphQL, which its proxy refuses), so the post goes through the repository's
  Actions: `idea file` queues it on the notes branch, together with the Actions
  workflow that posts it as `github-actions[bot]` and removes it from the queue. A post
  whose category the repository lacks, or that GitHub does not create, stays queued and
  the run fails.
- Where the repository has Discussions turned off, `idea file` refuses and queues
  nothing.

## Notes and progress

- On a notes branch on each repository - the fork, or the repository itself - readable
  from any session on that project.
- Saved without being asked whenever they were edited: at the end of every turn and of
  the session, since a cloud session's container can be reclaimed without the session
  ending. A save that fails is shown to me and the edits wait in `CLAUDE.local.md`.

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
- GitHub's own deletion of a merged pull request's branch spares most branches the
  listing. The tool never turns it on: where it is off, it tells me, with the link, and
  I opt in.
- Issues and pull requests are only ever closed, never deleted.

## Where something is turned off

- The tool never changes a repository's settings itself: turned on, a feature changes
  the repository for everyone, and on a public fork issues make the findings public.
- Where issues are turned off, as they are on a new fork, the tool tells me exactly where
  to turn them on, with the link, and I opt in.
- Where Actions are turned off, the tool never turns them on itself: once on, they run
  every workflow on the repository - on a fork, the upstream's scheduled, release and
  bot workflows too - under my account. It tells me they are off, with the link, and I
  decide.
- A cloud session can see whether issues are on, but not whether Actions are on, so
  there the tool says nothing about Actions.

## How the agent reaches git and GitHub

- It reads git directly: status, diffs, history, and fetching.
- Every write - a branch, a commit, a push, a pull request, a stack, the notes - goes
  through the workflow's own commands, which check the rules above before writing. A
  plugin hook denies every direct write, so the rules cannot be skipped by accident.
- When that hook's runtime cannot run - missing or broken - the guard runs from the
  plugin's source on the standard library alone and judges every call as usual, reads
  included. When that fails too, a coarse stand-in denies every call naming git, gh,
  curl or wget, every GitHub tool and every write to git's configuration, and lets
  everything else run. Only when the stand-in cannot run either is every call blocked.
- That guard catches accidents, not intent: it reads only the command lines of git, gh,
  curl and wget, through shells and wrappers. A push run any other way - an
  interpreter, a build tool, a script - is caught by a `pre-push` hook the session
  start writes into the checkout, which refuses a push to anyone else's repository or
  to the default branch. It checks only pushes from a Claude Code session (where
  `CLAUDECODE` is set, which the guard refuses to change), so my own pushes from a
  terminal pass unchecked. A checkout with a `pre-push` hook of its own keeps it, and
  the session start says the workflow's is missing.
- A command the guard denies only because it cannot see what it runs - a program named
  by an expansion (`eval` among them), a shell reading its input, `xargs` - is shown to
  me, so I can judge how often that happens and whether the rule is worth its cost.
- Not covered: a write to GitHub's API from an interpreter or a script (including the
  domain model's clients called from a one-off snippet), and a push that skips hooks
  (`--no-verify`) from such a program. Only a token scoped to my repositories (a
  fine-grained token or a GitHub App) stops those, at GitHub.
- Nothing is ever force-pushed. A change low in a stack is an ordinary push; GitHub's
  "Rebase stack" moves the pull requests above it, and I merge stacks on GitHub.

## What the agent may do without asking

- push its own work branch
- fast-forward a fork's default branch to its upstream's, with `sync --upstream`
- save notes and progress
- mark its own throwaway branches as discarded, closing their open pull requests
- open a draft replacing one of its own (`draft --replaces <number>`), closing the old
  one; a stack the old one held is made again with the new one in its place
- close a pull request only as discarded or replaced, and only an open one from a work
  branch on my repository, labelled `closed by session`, with a comment saying why,
  telling me in chat
- open draft pull requests
- on the work branch's own open pull request: add or remove labels the repository has
  (`label`), rewrite its description and title (`describe` without a number), and
  reply to or resolve its review threads (`review`), resolving only once the branch's
  commits are pushed; unresolving a thread stays mine
- add a comment to a finding (`finding comment`)
- delete branches that are merged or marked discarded, still at the commit they were
  marked at (`cleanup`)
- in a cloud session, attach `LucaKro/GitHubWorkflow` or `LucaKro/basstler_domain_model`
  to the session, with push access, to list or file a finding there; never another
  account's copy of either

Everything else written to GitHub needs my go-ahead.

## What only I do

- Opening a fork's pull request on its upstream: `github-workflow upstream <fork>
  <branch>` opens it,
  ready for review, with the same title and a description linking back to the fork's
  pull request, which then links to it. It refuses a pull request that is not open, is
  stacked, or is open upstream already.
- No session runs it, not even with my go-ahead: the guard denies it, and the command
  refuses to run where Claude Code's command marker is set. `draft` on a fork ends the
  description with the command line, for me to copy, and `describe` keeps it there,
  once, whatever text it is given.
- A refusal tells me why, as its reason and what to do instead, without a traceback.
- `github-workflow` runs the workflow on any machine with the plugin: the runtime install
  writes it to `~/.local/bin`, says so when that is not on my `PATH`, and never replaces
  a file of that name that is not the workflow's.

## How work is done

- A task such as "do issue 1": small, clear tasks go straight to code, failing test
  first; larger ones get a plan I approve first. For a finding, that failing test is
  its proof.
- Pull requests stay small through a standing note, not through a measured limit.
- A pull request's description and title follow its pushed commits: `describe` rewrites
  them on any open pull request of mine, a draft or ready for review, on my go-ahead,
  and on the work branch's own without asking; a closed or merged one keeps its own.
- Starting a work branch from the default branch also fast-forwards my local default
  branch to GitHub's, unless it has commits of its own.
- Dependent pull requests are rare, and use GitHub's native stacks when they happen,
  restacked and merged by GitHub.
- A work branch takes in the default branch's new commits with `sync --base`: a merge,
  committed as me, never a rebase or a force. That includes the bottom pull request of
  a stack, which targets the default branch; a branch higher in a stack takes in the
  one below with `sync --on`, or is left to GitHub's *Rebase stack*.
- A merge that conflicts is left in progress, its files named. The session resolves
  them and finishes it with `sync --continue <files>`, which refuses while a conflict
  is still marked or a file still conflicts, or undoes it with `sync --abort`. Nothing
  is committed or pushed on the branch meanwhile.
- A work branch builds on another open pull request of my repository before it is
  merged with `sync --on <number>`, which merges that pull request's branch the same
  way. A draft of a finding stacked on it (`draft --finding --on <number>`) rechecks
  the proof on that branch rather than on the default branch.

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
