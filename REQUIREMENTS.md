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
  dependencies, and the plugin ships the domain model beside the workflow
  (`domain_model/src`), so the runtime runs the source of the plugin's own copy, the
  two always of one commit. A session whose network reaches no package index still
  gets the guard.
- A new runtime is switched to only once its guard works and its commands load, so a
  copy that cannot build one leaves the runtime in use alone; a test builds a runtime
  from the plugin's own source, so a change breaking the build fails before it is
  merged.
- A plugin synced after the session started brings hooks newer than the runtime the
  session start installed. Each hook runs its own plugin copy's code, with the runtime
  only supplying the libraries, so a hook never fails for a module the older runtime
  lacks.
- The cloud environment sets the git identity commits are authored with
  (`GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL`, `GIT_COMMITTER_NAME`, `GIT_COMMITTER_EMAIL`).
- `scripts/cloud-check.sh` checks a cloud session end to end and publishes its report
  to the results branch.

## What a session starts with

Loaded automatically, kept as small as possible and produced by code rather than by the
agent:

- my standing notes
- this branch's progress
- in my terminal, each section's heading is bold bright blue, a pull request's status
  tags green, and a finding's priority tag graded in magenta, critical white on
  magenta down to low dimmed: colours no tone of a line uses
- every pull request and issue the workflow names is a Markdown link to its page,
  `[#62](https://github.com/<owner>/<name>/pull/62)`, and the model names them the
  same way in chat
- one line per open pull request on the repository, grouped under headings: open
  upstream, drafts, ready for review. Those I labelled `pull request: shelved`
  (created for me to pick) are left out, and a session leaves them alone unless I name
  one
- the open findings, each named with its priority, grouped under headings: waiting on
  my review, accepted and proven, accepted and not proven yet, accepted and marked
  unproven. Shelved and rejected findings are left out
- a group with nothing in it is left out
- warnings about this branch's pull request
- what was brought up to date: the fork's default branch and the work branch, as
  described under what the agent may do without asking, and what could not be
- where the project declares the tool managing its environment, such as uv (a
  `uv.lock` or a `[tool.uv]` table): to set the environment up with that tool, its
  development extras named (`uv sync --extra dev`), whenever tests need it, and never
  to install the project's packages by hand. The workflow never runs the tool itself.
  When the tool is not installed, that is left for me to decide. The instruction
  itself goes to the model alone, never to my terminal: it is not for me to read on
  every prompt.

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
  what should have. The notes header says how; `finding list --repository` shows first
  whether it is filed already. Every refusal, the guard's and the commands', says only
  why, what to run instead and never to get around it, with a script or in any other
  way - a session asks me, or files it - and points to the notes for how to report it,
  so the command list and the filing hint are not repeated each time. Command lines
  the workflow prints name the launcher, `github-workflow`, where the one on the path
  runs the same interpreter, and the interpreter's full path otherwise.
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
  default branch. Sessions tidy them too, so no repository needs the workflow for it:
  at session start and in `finding list`, of each kind of finding label an open
  finding carries several of, the one I added last stays, as the issue's events show,
  and an open finding labelled *incorrect* is closed as not planned. What was tidied
  is said.
- Apart from its stage, a finding may be *proven*: a test fails on the default branch
  as GitHub has it, and is posted on the issue - with the commit it failed on - but
  never committed. A finding stays *unreviewed* when proven; being proven never
  replaces my review.
- The filing session proves a finding when a failing test is easy to write; otherwise
  it files it unproven.
- A test passing on the default branch proves nothing: a bug only on a work branch is
  no finding. Neither does a test that is broken rather than failing - one that cannot
  be collected or set up, fails on its own import, name or syntax error, or on a file
  of its own, under the tests' directory, that the default branch lacks.
- The test imports the default branch's packages, a uv workspace's members' included,
  ahead of any the interpreter has installed from the working checkout.
- The code runs the test and decides whether it proves the finding; the agent's word
  is not taken for it. A proof counts only when posted by me or by the account the
  workflow writes as.
- A session works on a finding only when I ask it to, never because it found one easy
  to prove. Working on an *accepted* finding starts with proving it; when no failing
  test can be written, the session marks it *unproven* with the reason, and leaves it
  to me. An unproven finding gets no draft.
- A test that needs another open pull request's changes, or a bug that exists only on
  a pull request's branch, is proven and rechecked there: `finding prove` and `finding
  recheck` take `--on <pull request>`, or `--on <branch>` for a branch without one,
  and the proof records the branch and commit it failed on. The pull request has to be
  open and its branch on my repository.
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
  discarded at, all in one push, each under a lease on that commit, so a branch that
  moved meanwhile is kept. Where the session may not delete
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
- Where Discussions are turned off, the tool tells me the same way: ideas and the
  session log are posted there, and without them `idea file` refuses and nothing is
  entered in the log.
- Where Actions are turned off, the tool never turns them on itself: once on, they run
  every workflow on the repository - on a fork, the upstream's scheduled, release and
  bot workflows too - under my account. It tells me they are off, with the link, and I
  decide.
- A cloud session can see whether issues are on, but not whether Actions are on. It can
  see each workflow's state, so wherever one of the notes branch's workflows is off -
  as on a fork whose workflows were never turned on, or after GitHub turned them off
  for inactivity - the session start says so, with the link to the Actions page.

## How the agent reaches git and GitHub

- It reads git directly: status, diffs, history, and fetching.
- It reads GitHub directly too, GraphQL included: `gh api graphql` with a document of
  queries alone, given in place, is a read; a mutation, a subscription, a document read
  from a file, or any option that sends more is a write.
- Every write - a branch, a commit, a push, a pull request, a stack, the notes - goes
  through the workflow's own commands, which check the rules above before writing. A
  plugin hook denies every direct write, so the rules cannot be skipped by accident.
- When that hook's runtime cannot run - missing or broken - the guard runs from the
  plugin's source on the standard library alone and judges every call as usual, reads
  included. When that fails too, a coarse stand-in denies every call naming git, gh,
  curl or wget, every GitHub tool and every write to git's configuration, and lets
  everything else run. Only when the stand-in cannot run either is every call blocked.
- That guard catches accidents, not intent: it reads only the command lines of git, gh,
  curl and wget, through shells, wrappers and any other program given one of them,
  except those that never run their arguments, such as `echo` or `grep`; a text in
  single quotes it reads as text. It also denies a redirection or a program such as
  `rm`, `cp` or `sed` writing where git reads its configuration or hooks, and any
  builtin setting `CLAUDECODE`. A push run any other way - an
  interpreter, a build tool, a script - is caught by a `pre-push` hook the session
  start writes into the checkout, which refuses a push to anyone else's repository or
  to the default branch. It checks only pushes from a Claude Code session (where
  `CLAUDECODE` is set, which the guard refuses to change), so my own pushes from a
  terminal pass unchecked. A checkout with a `pre-push` hook of its own keeps it, and
  the session start says the workflow's is missing.
- A command the guard denies only because it cannot see what it runs - a program named
  by an expansion (`eval` among them), a shell reading its input, `xargs`, `source` of
  a stream, curl or wget reading options from elsewhere or sending to an address an
  expansion names - is shown to
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
- keep branches up to date on its own, at session start and before `push`, `draft` and
  `describe` of the work branch's own pull request: a fork's default branch is
  fast-forwarded to its upstream's when it is behind and has no commits of its own,
  then the work branch is merged with the branch its open pull request targets (the
  default branch when it has none) when it is behind, its working tree holds no
  changes and `git merge-tree` shows the merge is clean. Never rebased or forced. What
  cannot be done this way - a conflict, uncommitted changes, a fork's own commits - is
  reported instead, for the session to settle with `sync`
- save notes and progress
- mark its own throwaway branches as discarded, closing their open pull requests
- open a draft replacing one of its own (`draft --replaces <number>`), closing the old
  one; a stack the old one held is made again with the new one in its place
- close a pull request only as discarded, replaced or merged upstream, and only an open
  one from a work branch on my repository, labelled `closed by session`, with a comment
  saying why, telling me in chat. At session start, a fork's pull request labelled
  `opened upstream` whose pull request upstream was merged - found through GitHub's
  search, which a cloud session reaches - is closed as merged upstream, linking it, and
  the pull request stacked on it moves onto the default branch, the stack made again
  from the open ones above. One the fork merged already, as the fork sync does, still
  has what is stacked on it moved
- open draft pull requests, labelling every issue a draft's description closes
  (`Fixes #N`) `pull request opened`, created where my repository lacks it; a pull
  request a session closes unmerged takes the label off its issues again, and a draft
  replacing one labels its own issues after the old one is closed
- on the work branch's own open pull request: add or remove labels the repository has
  (`label`), except `pull request: shelved`, which only I set, rewrite its description
  and title (`describe` without a number), and reply to or resolve its review threads
  (`review`), resolving only once the branch's commits are pushed; unresolving a
  thread stays mine
- read the reviews and threads of the pull request it has open upstream, which `review
  list` shows after the own pull request's, each comment with its address: directly
  with my login, or, from a cloud session, through the fork's Actions, which read them
  for a request on the notes branch and save GitHub's answers there; when they start no
  run for it within a minute and a half, it asks once more, and when they start none
  then either, or the run fails, `review list` says so below the own pull request's
  threads, which it always lists, with the link to turn them on or to the run's log. The workflow lives only on
  the notes branch, never on the default branch or upstream. Nothing is ever
  written upstream: having changed something for an upstream comment, the session says
  so on the own pull request with `review addressed <address> --body-file <what
  changed>`, which links the comment
- add a comment to a finding (`finding comment`), a closed one too, such as a correction
  after the fix landed, and on another of my repositories with `--repository`
- delete branches that are merged or marked discarded, still at the commit they were
  marked at (`cleanup`)
- in a cloud session, attach `LucaKro/GitHubWorkflow` or `LucaKro/basstler_domain_model`
  to the session, with push access, to list or file a finding there; never another
  account's copy of either

What a session closes or deletes on its own - a finding closed as fixed, a pull request
closed as discarded or replaced, the branches `cleanup` deletes - is also entered in the
repository's "Session log" discussion, in the General category: one comment per entry,
with its time and the session's branch, posted through Actions like an idea. The log is
started with its first entry; I pin it myself, since GitHub's API cannot. Nothing is
entered where the repository has Discussions turned off; the `closed by session` label
still marks what was closed.

The guard never asks me to confirm a workflow command, and neither does auto mode: the
plugin's mod approves a command line that is exactly one workflow command a session
runs on its own, through `github-workflow`, with at most `cd` before it and `head` or
`tail` after it, once nothing refused it. What is mine to decide - a finding's stage
(`finding accept`, `shelve`, `reject`), its priority or text (`finding prioritize`,
`edit`), another pull request's description (`describe <number>`) or its place in a
stack (`stack on`) - the mod never approves, and a session does it only when I said so
in the conversation.
Everything else written to GitHub needs me to ask for it.

## What only I do

- Opening a fork's pull request on its upstream: `github-workflow upstream <fork>
  <branch>` opens it,
  ready for review, with the same title and a description linking back to the fork's
  pull request, which then links to it and is labelled `opened upstream` (blue, created
  on the fork when missing), so the fork's list shows what has gone upstream. It
  refuses a pull request that is not open, is stacked, or is open upstream already, and
  a refused run labels nothing.
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
  them on any open pull request of mine, a draft or ready for review, when I say so,
  and on the work branch's own without asking; a closed or merged one keeps its own.
- Starting a work branch from the default branch also fast-forwards my local default
  branch to GitHub's, unless it has commits of its own.
- `branch switch` also switches to a branch only GitHub has, fetching it first.
- Dependent pull requests are rare, and use GitHub's native stacks when they happen,
  restacked and merged by GitHub. `draft --on` checks that the pull request below can
  take one more on top before it opens anything: a stack is a single line, so one that
  already has an open pull request on it is refused with no draft opened.
  If stacking the draft, or closing the pull request it replaces, fails once the
  draft is open, the refusal names the opened draft, so it is not opened twice.
- A work branch takes in the default branch's new commits with `sync --base`: a merge,
  committed as me, never a rebase or a force. That includes the bottom pull request of
  a stack, which targets the default branch; a branch higher in a stack takes in the
  one below with `sync --on`, or is left to GitHub's *Rebase stack*.
- A merge that conflicts is left in progress, its files named. The session resolves
  them and finishes it with `sync --continue <files>`, which refuses while a conflict
  is still marked or a file still conflicts, and takes a file deleted as resolved by
  its removal, or undoes it with `sync --abort`. Nothing
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
